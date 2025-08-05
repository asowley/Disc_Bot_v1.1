from datetime import datetime, timezone
import json
import logging
import os
import asyncio
import aiomysql

import discord
from tools.EOS import EOS
from tools.player_display import build_player_list_embeds
from tools.connector import db_connector
from tools.database_tools import get_user_tribe_and_most_joined_server

class Monitor:
    '''
    A class to monitor a specific server and channel in a guild.

    server_number: The number of the server to monitor.
    type_of_monitor: The type of monitor (1 for server, 2 for channel).
    channel_id: The ID of the channel to send messages.
    guild_id: The ID of the guild where the channel is located.
    bot: The Discord bot instance.
    '''

    def __init__(self, server_number, type_of_monitor, channel_id, guild_id, bot):
        self.server_number = server_number
        self.type_of_monitor = int(type_of_monitor)  # Ensure it's always an int
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.bot = bot
        self.task = None
        self.stopped = False

    def start(self):
        # Start the monitor as an asyncio task
        if self.task is None or self.task.done():
            self.stopped = False
            self.task = asyncio.create_task(self._run_with_restart())

    async def stop(self):
        # Cancel the running task
        if self.task and not self.task.done():
            self.stopped = True
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _run_with_restart(self):
        # Internal: run the monitor, restart if cancelled
        while True:
            try:
                await self._run_monitor()
            except asyncio.CancelledError:
                if self.stopped:
                    logging.info(f"Monitor for server {self.server_number} has been stopped.")
                    break
                await asyncio.sleep(10)
            except Exception as e:
                logging.error(f"Monitor crashed with error: {e}, restarting...")
                await asyncio.sleep(10)

    async def _run_monitor(self):
        logging.info(f"Starting monitor (type {self.type_of_monitor}) for server {self.server_number} in channel {self.channel_id} of guild {self.guild_id}")
        if self.type_of_monitor == 1:
            await self.run_monitor_type_1()
        elif self.type_of_monitor == 2:
            await self.run_monitor_type_2()
        elif self.type_of_monitor == 3:
            await self.run_monitor_type_3()
        else:
            logging.error(f"Unknown monitor type: {self.type_of_monitor}")

    async def run_monitor_type_1(self):
        '''\nA single monitor loop for monitors of type 1.\n'''

        eos = EOS()
        server_info, total_players, _, _ = await eos.matchmaking(self.server_number)

        # --- JSON persistence setup ---
        monitors_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitors_minutes")
        os.makedirs(monitors_dir, exist_ok=True)
        json_path = os.path.join(monitors_dir, f"monitor_minutes_{self.server_number}.json")

        # Load previous data if exists
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                monitor_data = json.load(f)
            population_counts = monitor_data.get("population_counts", [])
            last_monitor_timestamp = monitor_data.get("last_timestamp", 0)
            last_channel_rename = monitor_data.get("last_channel_rename", 0)
        else:
            population_counts = []
            last_monitor_timestamp = 0
            last_channel_rename = 0

        balance = 0
        if population_counts:
            balance = total_players - population_counts[-1]

        # --- Discord embed logic (unchanged) ---
        if abs(balance) > 0:
            embed = discord.Embed(title=f"Monitor {self.server_number}", timestamp=datetime.now())

            if balance > 0:
                embed.colour = discord.Colour.blue()
            else:
                embed.colour = discord.Colour.dark_purple()

            embed.clear_fields()

            embed.add_field(
                name="Server Name",
                value=server_info['attributes']['SESSIONNAME_s'],
                inline=False
            )
            embed.add_field(
                name="Player Count",
                value=total_players,
                inline=False
            )
            embed.add_field(
                name="Last 60s Balance",
                value=f"{abs(balance)} {'players' if abs(balance) > 1 else 'player'} {'joined' if balance > 0 else 'left'}!",
                inline=False
            )

            # --- Send the embed to the channel ---
            guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
            if guild:
                channel = guild.get_channel(self.channel_id)
                if channel:
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        logging.error(f"[Monitor.py] Failed to send monitor message: {e}")

        # --- Channel rename logic ---
        now_ts = int(datetime.now().timestamp())
        channel_rename_interval = 5 * 60  # 5 minutes in seconds

        if now_ts - last_channel_rename >= channel_rename_interval:
            try:
                guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
                if guild:
                    channel = guild.get_channel(self.channel_id)
                    if channel:
                        # Rename to server_number-population as requested
                        new_name = f"{self.server_number}-{total_players}"
                        await channel.edit(name=new_name)
                        logging.info(f"[Monitor.py] Renamed channel {self.channel_id} to {new_name}")
                        last_channel_rename = now_ts
            except Exception as e:
                logging.error(f"[Monitor.py] Failed to rename channel {self.channel_id}: {e}")

        # --- Update JSON persistence after sending monitor ---
        population_counts.append(total_players)
        if len(population_counts) > 60:
            population_counts = population_counts[-60:]
        last_monitor_timestamp = now_ts

        # Save updated data
        with open(json_path, "w") as f:
            json.dump({
                "server_number": self.server_number,
                "last_timestamp": last_monitor_timestamp,
                "population_counts": population_counts,
                "last_channel_rename": last_channel_rename
            }, f)

        # --- Adjust sleep to keep interval consistent ---
        sleep_time = max(0, round(last_monitor_timestamp + 60 - now_ts))
        await asyncio.sleep(sleep_time)

    async def run_monitor_type_2(self):
        '''\nA single monitor loop for monitors of type 2.\n'''

        eos = EOS()
        try:
            # Efficiently fetch room_id from DB for this server
            conn = await db_connector()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT room_id FROM ark_servers_new WHERE ark_server = %s", (self.server_number,)
                )
                row = await cursor.fetchone()
                room_id = row[0] if row else 0
            if room_id == 0:
                logging.error(f"[Monitor.py] No room_id found for server {self.server_number}.")
                return

            # Get player puids and info using room_id
            puids = await eos.players(self.server_number, room_id)
            puids_info = await eos.info(puids)
            server_info, total_players, max_players, ip_and_port = await eos.matchmaking(self.server_number)
            custom_server_name = server_info["attributes"]["CUSTOMSERVERNAME_s"]
        except Exception as e:
            logging.error(f"[Monitor.py] Error in run_monitor_type_2: {e}")
            await asyncio.sleep(30)
            return

        # Build embeds using the shared function
        embeds = await build_player_list_embeds(
            self.server_number, puids_info, custom_server_name, total_players, max_players, conn
        )

        # Purge previous messages before sending new embeds
        guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
        if guild:
            channel = guild.get_channel(self.channel_id)
            if channel:
                try:
                    await channel.purge(limit=5)
                except Exception as e:
                    logging.error(f"[Monitor.py] Failed to purge messages: {e}")
                for embed in embeds:
                    await channel.send(embed=embed)
        await asyncio.sleep(15)  # Check every 15 seconds (adjust as needed)

    async def run_monitor_type_3(self):
        eos = EOS()
        monitors_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitors_minutes")
        os.makedirs(monitors_dir, exist_ok=True)
        json_path = os.path.join(monitors_dir, f"monitor_type3_{self.server_number}.json")

        # Load previous player set if exists
        if os.path.exists(json_path):
            with open(json_path, "r") as f:
                monitor_data = json.load(f)
            prev_players = set(monitor_data.get("puids", []))
        else:
            prev_players = set()

        # Get current players
        server_info, total_players, max_players, _ = await eos.matchmaking(self.server_number)
        conn = await db_connector()
        async with conn.cursor() as cursor:
            await cursor.execute(
                "SELECT room_id FROM ark_servers_new WHERE ark_server = %s", (self.server_number,)
            )
            row = await cursor.fetchone()
            room_id = row[0] if row else 0

        if room_id == 0:
            logging.error(f"[Monitor.py] No room_id found for server {self.server_number}.")
            await asyncio.sleep(30)
            return

        puids = await eos.players(self.server_number, room_id)
        puids_info = await eos.info(puids)
        current_players = set(player['puid'] for player in puids_info)

        joined = current_players - prev_players
        left = prev_players - current_players

        guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
        if guild:
            channel = guild.get_channel(self.channel_id)
            if channel:
                # Announce joins
                for puid in joined:
                    player = next((p for p in puids_info if p['puid'] == puid), None)
                    display_name = player['display_name'] if player else "Unknown"
                    # Fetch tribe and most joined server
                    tribe, most_joined_server = await get_user_tribe_and_most_joined_server(puid)
                    embed = discord.Embed(
                        title=f"{display_name} JOINED {self.server_number} [{total_players}/{max_players}]",
                        colour=discord.Colour.green(),
                        timestamp=datetime.now()
                    )
                    embed.description = f"Most joined server: `{most_joined_server}`\nTribe: `{tribe}`"
                    embed.set_footer(text=f"PUID: {puid}")
                    await channel.send(embed=embed)
                # Announce leaves
                # Build a dict of previous puid -> display_name
                prev_display_names = {}
                if os.path.exists(json_path):
                    with open(json_path, "r") as f:
                        monitor_data = json.load(f)
                    prev_display_names = monitor_data.get("display_names", {})

                # ... after you get puids_info ...
                current_display_names = {player['puid']: player.get('display_name', 'Unknown') for player in puids_info}

                # Announce leaves
                for puid in left:
                    display_name = prev_display_names.get(puid, "Unknown")
                    tribe, most_joined_server = await get_user_tribe_and_most_joined_server(puid)
                    embed = discord.Embed(
                        title=f"{display_name} LEFT SERVER {self.server_number} [{total_players}/{max_players}]",
                        colour=discord.Colour.red(),
                        timestamp=datetime.now()
                    )
                    embed.description = f"Most joined server: `{most_joined_server}`\nTribe: `{tribe}`"
                    embed.set_footer(text=f"PUID: {puid}")
                    await channel.send(embed=embed)

        # Save current player set and display names for next run
        with open(json_path, "w") as f:
            json.dump({
                "puids": list(current_players),
                "display_names": current_display_names
            }, f)

        await asyncio.sleep(30)  # Check every 30 seconds (adjust as needed)




