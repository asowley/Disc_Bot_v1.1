import logging
from tools.Monitor import Monitor
from tools.connector import db_connector
import aiomysql
import asyncio
from tools.all_servers_monitor import monitor_all_servers

class Monitor_Manager:
    def __init__(self, bot):
        self.monitors = {}
        self.bot = bot
        self.all_servers_monitor_task = None

    async def start_monitors(self):
        # Start all individual monitors
        print(self.monitors)
        for monitor in self.monitors.values():
            monitor.start()  # <-- No await needed
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
        conn = await db_connector()
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT ark_server, type, channel_id, guild_id FROM monitors_new_upd")
            rows = await cursor.fetchall()
            for row in rows:
                key = (row['ark_server'], row['type'], row['channel_id'])
                if key not in self.monitors:
                    monitor = Monitor(
                        row['ark_server'],
                        row['type'],
                        row['channel_id'],
                        row['guild_id'],
                        self.bot
                    )
                    self.monitors[key] = monitor
        logging.info(f"Loaded {len(self.monitors)} monitors from database.")

    async def add_monitor(self, server_number, type_of_monitor, channel_id, guild_id):
        key = (server_number, type_of_monitor, channel_id)
        if key in self.monitors:
            logging.warning(f"Monitor for server {server_number}, type {type_of_monitor}, channel {channel_id} already exists.")
            return

        monitor = Monitor(server_number, type_of_monitor, channel_id, guild_id, self.bot)
        self.monitors[key] = monitor
        await monitor.start()
        logging.info(f"Added monitor for server {server_number}, type {type_of_monitor}, channel {channel_id}, guild {guild_id}.")

    async def remove_monitor(self, server_number, type_of_monitor, channel_id, guild_id):
        key = (server_number, type_of_monitor, channel_id)
        if key not in self.monitors:
            logging.warning(f"Monitor for server {server_number}, type {type_of_monitor}, channel {channel_id} does not exist.")
            return

        monitor = self.monitors.pop(key)
        await monitor.stop()
        logging.info(f"Removed monitor for server {server_number}, type {type_of_monitor}, channel {channel_id}, guild {guild_id}.")
