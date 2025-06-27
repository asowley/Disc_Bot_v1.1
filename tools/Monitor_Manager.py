import logging
from Monitor import Monitor
from tools.connector import db_connector
import aiomysql

class Monitor_Manager:
    def __init__(self, bot):
        self.monitors = {}
        self.bot = bot

    async def start_monitors(self):
        for monitor in self.monitors.values():
            await monitor.start()

    async def load_monitors_from_db(self):
        conn = await db_connector()
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("SELECT ark_server, type, channel_id, guild_id FROM monitors_new")
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
        # Optionally, you can insert the new monitor into the DB here as well
        if (server_number, type_of_monitor, channel_id) in self.monitors:
            logging.warning(f"Monitor for server {server_number}, type {type_of_monitor}, channel {channel_id} already exists.")
            return

        # Add to database
        conn = await db_connector()
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                INSERT INTO monitors_new (ark_server, type, channel_id, guild_id)
                VALUES (%s, %s, %s, %s)
                """,
                (server_number, type_of_monitor, channel_id, guild_id)
            )
            await conn.commit()

        monitor = Monitor(server_number, type_of_monitor, channel_id, guild_id, self.bot)
        self.monitors[(server_number, type_of_monitor, channel_id)] = monitor
        await monitor.start()
        logging.info(f"Added monitor for server {server_number}, type {type_of_monitor}, channel {channel_id}, guild {guild_id}.")

    async def remove_monitor(self, server_number, type_of_monitor, channel_id, guild_id):
        key = (server_number, type_of_monitor, channel_id)
        if key not in self.monitors:
            logging.warning(f"Monitor for server {server_number}, type {type_of_monitor}, channel {channel_id} does not exist.")
            return

        # Remove from database
        conn = await db_connector()
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                DELETE FROM monitors_new
                WHERE ark_server = %s AND type = %s AND channel_id = %s AND guild_id = %s
                """,
                (server_number, type_of_monitor, channel_id, guild_id)
            )
            await conn.commit()

        monitor = self.monitors.pop(key)
        await monitor.stop()
        logging.info(f"Removed monitor for server {server_number}, type {type_of_monitor}, channel {channel_id}, guild {guild_id}.")
