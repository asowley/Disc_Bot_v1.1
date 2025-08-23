# Manages multiple monitors and handles their lifecycle
import logging
from tools.Monitor import Monitor
from tools.connector import db_connector
import aiomysql
import asyncio
from tools.all_servers_monitor import monitor_all_servers

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
        conn = await db_connector()
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Fetch all monitors from the database
            await cursor.execute("""
                SELECT ark_server, type, channel_id, guild_id
                FROM monitors_new_upd
            """)
            monitors = await cursor.fetchall()

            # Fetch all alerts from the database
            await cursor.execute("""
                SELECT server_number, guild_id, alert_channel, population_change
                FROM alert_servers
            """)
            alerts = await cursor.fetchall()

            # Create a mapping of (server_number, guild_id) to alert data
            alert_mapping = {
                (alert['server_number'], alert['guild_id']): {
                    'alert_channel': alert['alert_channel'],
                    'population_change': alert['population_change']
                }
                for alert in alerts
            }

            # Initialize monitors
            for monitor_data in monitors:
                server_number = monitor_data['ark_server']
                type_of_monitor = monitor_data['type']
                channel_id = monitor_data['channel_id']
                guild_id = monitor_data['guild_id']

                # Get alert data if it exists
                alert_data = alert_mapping.get((server_number, guild_id))
                alert_channel_id = alert_data['alert_channel'] if alert_data else None
                population_change_threshold = alert_data['population_change'] if alert_data else None

                # Create a new Monitor instance
                monitor = Monitor(
                    server_number,
                    type_of_monitor,
                    channel_id,
                    guild_id,
                    self.bot,
                    alert_channel_id=alert_channel_id,
                    population_change_threshold=population_change_threshold
                )

                # Start the monitor
                monitor.start()

                # Add the monitor to the list
                self.monitors.append(monitor)

        logging.info(f"Loaded {len(self.monitors)} monitors from database.")

    async def add_monitor(self, server_number, type_of_monitor, channel_id, guild_id):
        """
        Add a new monitor to the list.
        """
        # Check if a monitor with the same server_number, type_of_monitor, and channel_id already exists
        for monitor in self.monitors:
            if (
                monitor.server_number == server_number and
                monitor.type_of_monitor == type_of_monitor and
                monitor.channel_id == channel_id
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
                monitor.server_number == server_number and
                monitor.type_of_monitor == type_of_monitor and
                monitor.channel_id == channel_id
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
        for monitor in self.monitors: 
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
                monitor.server_number == server_number and
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
