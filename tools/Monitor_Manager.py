# Manages multiple monitors and handles their lifecycle
import logging
from tools.Monitor import Monitor
from tools.connector import db_connector
import aiomysql
import asyncio
from tools.all_servers_monitor import monitor_all_servers
import time

class Monitor_Manager:
    def __init__(self, bot):
        self.monitors = []  # Use a list to store monitors
        self.bot = bot
        self.all_servers_monitor_task = None

    async def start_monitors(self):
        """
        Start all individual monitors.
        """
        for monitor in self.monitors:  # Iterate directly over the list
            monitor.start()  # No await needed
        # Start or restart the all_servers_monitor as a background task
        async def run_all_servers_monitor_with_restart():
            while True:
                try:
                    await monitor_all_servers()
                except asyncio.CancelledError:
                    logging.info("all_servers_monitor task cancelled.")
                    break
                except Exception as e:
                    logging.error(f"all_servers_monitor crashed with error: {e}, restarting in 5 seconds.")
                    await asyncio.sleep(5)
        # if not self.all_servers_monitor_task or self.all_servers_monitor_task.done():
        #     loop = asyncio.get_running_loop()
        #     self.all_servers_monitor_task = loop.create_task(run_all_servers_monitor_with_restart())
        #     logging.info("Started all_servers_monitor as a background task.")

    async def load_monitors_from_db(self):
        """
        Load all monitors from the database and initialize them.
        """
        t0 = time.monotonic()
        logging.info("[Monitor_Manager] load_monitors_from_db: start")
        conn = await db_connector()
        try:
            # ---------------- Monitors ----------------
            t_m0 = time.monotonic()
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                try:
                    logging.info("[Monitor_Manager] Fetching monitors from monitors_new_upd...")
                    # Timeout wrappers to detect stalls
                    await asyncio.wait_for(cursor.execute("""
                        SELECT ark_server, type, channel_id, guild_id
                        FROM monitors_new_upd
                    """), timeout=10)
                    monitors = await asyncio.wait_for(cursor.fetchall(), timeout=10)
                    logging.info(f"[Monitor_Manager] Monitors fetched: count={len(monitors)} (took {(time.monotonic()-t_m0):.3f}s)")
                except asyncio.TimeoutError:
                    logging.error("[Monitor_Manager] Timeout while fetching monitors from DB.")
                    return
                except Exception as e:
                    logging.error(f"[Monitor_Manager] Failed to fetch monitors: {e}")
                    return

                # Initialize monitors
                init_ok = 0
                for idx, monitor_data in enumerate(monitors):
                    try:
                        server_number = str(monitor_data['ark_server'])
                        type_of_monitor = int(monitor_data['type'])
                        channel_id = int(monitor_data['channel_id'])
                        guild_id = int(monitor_data['guild_id'])

                        logging.debug(f"[Monitor_Manager] Init monitor[{idx}] "
                                      f"server={server_number}, type={type_of_monitor}, "
                                      f"channel={channel_id}, guild={guild_id}")
                        monitor = Monitor(server_number, type_of_monitor, channel_id, guild_id, self.bot)
                        monitor.start()
                        self.monitors.append(monitor)
                        init_ok += 1
                    except Exception as e:
                        logging.error(f"[Monitor_Manager] Failed to init/start monitor {monitor_data}: {e}")

                logging.info(f"[Monitor_Manager] Initialized monitors: ok={init_ok}/{len(monitors)}; total_in_memory={len(self.monitors)}")

            # ---------------- Alerts ----------------
            logging.info("[Monitor_Manager] Loading alerts for monitors from database.")
            t_a0 = time.monotonic()
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                try:
                    logging.info("[Monitor_Manager] Fetching alerts from alert_servers...")
                    await asyncio.wait_for(cursor.execute("""
                        SELECT server_number, guild_id, population_change, alert_channel
                        FROM alert_servers
                    """), timeout=10)
                    alerts = await asyncio.wait_for(cursor.fetchall(), timeout=10)
                    logging.info(f"[Monitor_Manager] Alerts fetched: count={len(alerts)} (took {(time.monotonic()-t_a0):.3f}s)")
                    if alerts:
                        sample = alerts[:3]
                        logging.debug(f"[Monitor_Manager] Alerts sample(3): {sample}")
                except asyncio.TimeoutError:
                    logging.error("[Monitor_Manager] Timeout while fetching alerts from DB.")
                    return
                except Exception as e:
                    logging.error(f"[Monitor_Manager] Failed to fetch alerts from alert_servers: {e}")
                    return

                # Map alerts to monitors
                applied = 0
                for idx, alert_data in enumerate(alerts):
                    try:
                        server_number = str(alert_data['server_number'])
                        guild_id = int(alert_data['guild_id'])
                        population_change_threshold = int(alert_data['population_change'])
                        alert_channel_id = int(alert_data['alert_channel'])

                        logging.debug(f"[Monitor_Manager] Apply alert[{idx}] server={server_number}, guild={guild_id}, "
                                      f"thresh={population_change_threshold}, channel={alert_channel_id}; "
                                      f"monitors_in_memory={len(self.monitors)}")

                        success = await self.add_alert_to_monitor(
                            server_number=server_number,
                            guild_id=guild_id,
                            alert_channel_id=alert_channel_id,
                            population_change_threshold=population_change_threshold
                        )

                        if success:
                            applied += 1
                            logging.info(
                                f"[Monitor_Manager] Loaded alert OK: server={server_number}, guild={guild_id}, "
                                f"channel={alert_channel_id}, threshold={population_change_threshold}"
                            )
                        else:
                            logging.warning(f"[Monitor_Manager] No matching type 1 monitor for alert: server={server_number}, guild={guild_id}")
                    except Exception as e:
                        logging.error(f"[Monitor_Manager] Failed to apply alert {alert_data}: {e}")

                logging.info(f"[Monitor_Manager] Alerts applied: {applied}/{len(alerts)}")

            logging.info(f"[Monitor_Manager] load_monitors_from_db: done in {(time.monotonic()-t0):.3f}s; monitors_in_memory={len(self.monitors)}")
        except asyncio.CancelledError:
            logging.warning("[Monitor_Manager] load_monitors_from_db cancelled.")
            raise
        except Exception as e:
            logging.error(f"[Monitor_Manager] Unexpected error in load_monitors_from_db: {e}")
        finally:
            try:
                conn.close()
                logging.debug("[Monitor_Manager] DB connection closed.")
            except Exception:
                pass

    async def add_monitor(self, server_number, type_of_monitor, channel_id, guild_id):
        """
        Add a new monitor to the list.
        """
        # Check if a monitor with the same server_number, type_of_monitor, and channel_id already exists
        for monitor in self.monitors:
            if (
                str(monitor.server_number) == str(server_number) and
                str(monitor.type_of_monitor) == str(type_of_monitor) and
                str(monitor.channel_id) == str(channel_id)
            ):
                logging.warning(f"Monitor for server {server_number}, type {type_of_monitor}, channel {channel_id} already exists.")
                return

        # Create and start the new monitor
        monitor = Monitor(server_number, type_of_monitor, channel_id, guild_id, self.bot)
        self.monitors.append(monitor)
        monitor.start()
        logging.info(f"Added monitor for server {server_number}, type {type_of_monitor}, channel {channel_id}, guild {guild_id}.")

    async def remove_monitor(self, server_number, type_of_monitor, channel_id, guild_id):
        """
        Remove an existing monitor from the list.
        """
        # Find the monitor to remove
        for monitor in self.monitors:
            if (
                str(monitor.server_number) == str(server_number) and
                str(monitor.type_of_monitor) == str(type_of_monitor) and
                str(monitor.channel_id) == str(channel_id)
            ):
                # Stop and remove the monitor
                self.monitors.remove(monitor)
                await monitor.stop()
                logging.info(f"Removed monitor for server {server_number}, type {type_of_monitor}, channel {channel_id}, guild {guild_id}.")
                return

        logging.warning(f"Monitor for server {server_number}, type {type_of_monitor}, channel {channel_id} does not exist.")

    async def add_alert_to_monitor(self, server_number, guild_id, alert_channel_id, population_change_threshold):
        """
        Add an alert to an existing monitor of type 1.
        """
        logging.debug(f"[Monitor_Manager] add_alert_to_monitor: server={server_number}, guild={guild_id}, "
                      f"channel={alert_channel_id}, threshold={population_change_threshold}, "
                      f"monitors_in_memory={len(self.monitors)}")

        for i, monitor in enumerate(self.monitors):
            if (
                str(monitor.server_number) == str(server_number) and  # Convert both to strings for comparison
                monitor.guild_id == guild_id and
                monitor.type_of_monitor == 1
            ):
                # Update the monitor's alert parameters
                monitor.alert_channel_id = alert_channel_id
                monitor.population_change_threshold = population_change_threshold
                logging.info(f"Added alert to monitor for server {server_number} in guild {guild_id}: "
                             f"alert_channel_id={alert_channel_id}, population_change_threshold={population_change_threshold}")
                return True  # Alert added successfully

        logging.warning(f"No monitor of type 1 found for server {server_number} in guild {guild_id} to add an alert.")
        return False  # No matching monitor found

    async def remove_alert_from_monitor(self, server_number, guild_id):
        """
        Remove an alert from an existing monitor of type 1.
        """
        for monitor in self.monitors:  # Iterate directly over the list
            if (
                str(monitor.server_number) == str(server_number) and
                monitor.guild_id == guild_id and
                monitor.type_of_monitor == 1
            ):
                # Clear the monitor's alert parameters
                monitor.alert_channel_id = None
                monitor.population_change_threshold = None
                logging.info(f"Removed alert from monitor for server {server_number} in guild {guild_id}.")
                return True  # Alert removed successfully

        logging.warning(f"No monitor of type 1 found for server {server_number} in guild {guild_id} to remove an alert.")
        return False  # No matching monitor found
