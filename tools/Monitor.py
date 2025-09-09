# Monitor a specific ark server
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
from tools.database_tools import get_user_tribe_and_most_joined_server, create_history_graph, store_info_to_db  # Import the function

class Monitor:
    '''
    A class to monitor a specific server and channel in a guild.

    server_number: The number of the server to monitor.
    type_of_monitor: The type of monitor (1 for server, 2 for channel).
    channel_id: The ID of the channel to send messages.
    guild_id: The ID of the guild where the channel is located.
    bot: The Discord bot instance.
    '''

    def __init__(self, server_number, type_of_monitor, channel_id, guild_id, bot, alert_channel_id=None, population_change_threshold=None):
        self.server_number = server_number
        self.type_of_monitor = int(type_of_monitor)  # Ensure it's always an int
        self.channel_id = channel_id
        self.alert_channel_id = alert_channel_id  # Initialize alert channel ID
        self.population_change_threshold = population_change_threshold  # Initialize population change threshold
        self.guild_id = guild_id
        self.bot = bot
        self.task = None
        self.stopped = False
        logging.info(
            f"Monitor initialized: "
            f"server_number={self.server_number}, "
            f"type_of_monitor={self.type_of_monitor}, "
            f"channel_id={self.channel_id}, "
            f"alert_channel_id={self.alert_channel_id}, "
            f"population_change_threshold={self.population_change_threshold}, "
            f"guild_id={self.guild_id}"
        )

    def start(self):
        # Start the monitor as an asyncio task
        logging.info(f"Starting monitor (type {self.type_of_monitor}) for server {self.server_number} in channel {self.channel_id} of guild {self.guild_id}")

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
        try:
            if self.type_of_monitor == 1:
                await self.run_monitor_type_1()
            elif self.type_of_monitor == 2:
                await self.run_monitor_type_2()
            elif self.type_of_monitor == 3:
                await self.run_monitor_type_3()
            else:
                logging.error(f"Unknown monitor type: {self.type_of_monitor}")
        except Exception as e:
            logging.error(f"Exception in _run_monitor for server {self.server_number}: {e}")

    # Safe extractor for server name to avoid `string indices must be integers`
    def _safe_server_name(self, server_info):
        try:
            if isinstance(server_info, dict):
                attrs = server_info.get('attributes')
                if isinstance(attrs, dict):
                    return (
                        attrs.get('CUSTOMSERVERNAME_s')
                        or attrs.get('SESSIONNAME_s')
                        or str(self.server_number)
                    )
            if isinstance(server_info, str) and server_info.strip():
                logging.debug(f"[Monitor.py] server_info is str; using as name. value='{server_info[:64]}'")
                return server_info
        except Exception as e:
            logging.error(f"[Monitor.py] Failed to extract server name: {e}")
        return str(self.server_number)

    # Normalize odd names like "error", "unknown", or "no server ..."
    def _normalize_server_name(self, name):
        try:
            s = (str(name) if name is not None else "").strip()
            low = s.lower()
            if not s or low == "error" or low == "unknown" or "no server" in low:
                fallback = str(self.server_number)
                logging.debug(f"[Monitor.py] Normalizing server name '{s}' -> '{fallback}'")
                return fallback
            return s
        except Exception as e:
            logging.error(f"[Monitor.py] Failed to normalize server name '{name}': {e}")
            return str(self.server_number)

    async def run_monitor_type_1(self):
        '''A single monitor loop for monitors of type 1.'''
        eos = EOS()
        graph_path = None
        offline = False

        # Attempt to fetch server info
        try:
            server_info, total_players, _, _ = await eos.matchmaking(self.server_number)
            logging.debug(f"[Monitor.py] matchmaking returned type(server_info)={type(server_info)}")
        except Exception as e:
            logging.error(f"[Monitor.py] Failed to fetch server info for server {self.server_number}: {e}")
            server_info = None
            total_players = None

        # If matchmaking fails, send a red embed indicating the server is offline
        if server_info is None:
            offline = True
            total_players = 0  # treat as 0 players for this minute
            guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
            if guild:
                channel = guild.get_channel(self.channel_id)
                if channel:
                    embed = discord.Embed(
                        title=f"Server {self.server_number} is Offline",
                        description="The server is currently unreachable or offline.",
                        colour=discord.Colour.red(),
                        timestamp=datetime.now()
                    )
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        logging.error(f"[Monitor.py] Failed to send offline embed for server {self.server_number}: {e}")

        # Default total_players to 0 if matchmaking failed or returned None
        if total_players is None:
            total_players = 0

        # --- Store player count in DB (store 0 when offline) ---
        try:
            await store_info_to_db(self.server_number, total_players)
        except Exception as e:
            logging.error(f"[Monitor.py] Failed to store player count in DB for server {self.server_number}: {e}")

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

        # --- Generate the history graph (skip when offline) ---
        if not offline:
            try:
                graph_path = await create_history_graph(self.server_number, 1)  # Last hour
            except Exception as e:
                logging.error(f"[Monitor.py] Failed to create history graph for server {self.server_number}: {e}")
                graph_path = None

        # --- Check for alerts (suppressed when total_players == 0 or offline by condition) ---
        if self.alert_channel_id and self.population_change_threshold is not None and total_players > 0:
            guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
            if guild:
                alert_channel = guild.get_channel(self.alert_channel_id)  # Use the alert channel
                if alert_channel:
                    # Check if the population change in the last 5 minutes meets the threshold
                    if len(population_counts) >= 5:
                        population_5_minutes_ago = population_counts[-5]
                        population_change = total_players - population_5_minutes_ago

                        # Skip alerts if any of the last 5 minutes had 0 population (likely recent crash)
                        last5 = population_counts[-5:]
                        if any(p == 0 for p in last5):
                            logging.info(f"[Monitor.py] Skipping alert: zero population within last 5 minutes "
                                         f"(last5={last5}) for server {self.server_number}")
                        else:
                            # Signed threshold logic
                            try:
                                threshold = int(self.population_change_threshold)
                            except Exception:
                                logging.error(f"[Monitor.py] Invalid alert threshold: {self.population_change_threshold}")
                                threshold = 0

                            # +threshold => joins (increase), -threshold => leaves (decrease)
                            should_alert = (
                                (threshold > 0 and population_change >= threshold) or
                                (threshold < 0 and population_change <= threshold)
                            )

                            logging.info(f"[Monitor.py] server={self.server_number} change={population_change} "
                                         f"threshold={threshold} should_alert={should_alert}")

                            if should_alert:
                                try:
                                    alert_type = "joined" if population_change > 0 else "left"
                                    magnitude = abs(population_change)
                                    embed = discord.Embed(
                                        title=f"ALERT: Population Change on Server {self.server_number}",
                                        description=(f"Population has {alert_type} by {magnitude} "
                                                     f"in the last 5 minutes.\nThreshold: {threshold}"),
                                        colour=discord.Colour.red(),
                                        timestamp=datetime.now()
                                    )
                                    embed.add_field(name="Current Population", value=total_players, inline=False)

                                    # Retry sending the embed with the graph up to 3 times
                                    for attempt in range(3):
                                        try:
                                            if graph_path:
                                                with open(graph_path, "rb") as f:
                                                    file_disc = discord.File(f, filename="image.png")
                                                    embed.set_image(url="attachment://image.png")
                                                    await alert_channel.send(embed=embed, file=file_disc)
                                            else:
                                                await alert_channel.send(embed=embed)
                                            break
                                        except Exception as e:
                                            logging.error(f"[Monitor.py] Failed to send alert (attempt {attempt + 1}): {e}")
                                            if attempt == 2:
                                                logging.error("[Monitor.py] Giving up on sending alert after 3 attempts.")
                                except Exception as e:
                                    logging.error(f"[Monitor.py] Failed to build/send alert embed: {e}")

        # --- Discord embed logic (skip for offline minutes to avoid duplicate messages) ---
        if not offline and abs(balance) > 0:
            embed = discord.Embed(title=f"Monitor {self.server_number}", timestamp=datetime.now())

            if balance > 0:
                embed.colour = discord.Colour.blue()
            else:
                embed.colour = discord.Colour.dark_purple()

            embed.clear_fields()

            # Use safe server name extraction
            server_name = self._safe_server_name(server_info)
            server_name = self._normalize_server_name(server_name)
            embed.add_field(
                name="Server Name",
                value=server_name,
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
                        # Retry sending the embed with the graph up to 3 times
                        for attempt in range(3):
                            try:
                                if graph_path:
                                    with open(graph_path, "rb") as f:
                                        file_disc = discord.File(f, filename="image.png")
                                        embed.set_image(url="attachment://image.png")
                                        await channel.send(embed=embed, file=file_disc)
                                else:
                                    await channel.send(embed=embed)
                                break  # Exit the retry loop if successful
                            except Exception as e:
                                logging.error(f"[Monitor.py] Failed to send monitor message or graph (attempt {attempt + 1}): {e}")
                                if attempt == 2:  # If the last attempt fails, log it
                                    logging.error(f"[Monitor.py] Giving up on sending monitor message after 3 attempts.")
                    except Exception as e:
                        logging.error(f"[Monitor.py] Failed to send monitor message or graph: {e}")

        # --- Channel rename logic (still runs; will show -0 when offline) ---
        now_ts = int(datetime.now().timestamp())
        channel_rename_interval = 5 * 60  # 5 minutes in seconds

        if now_ts - last_channel_rename >= channel_rename_interval:
            try:
                guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
                if guild:
                    channel = guild.get_channel(self.channel_id)
                    if channel:
                        new_name = f"{self.server_number}-{total_players}"
                        await channel.edit(name=new_name)
                        last_channel_rename = now_ts
            except Exception as e:
                logging.error(f"[Monitor.py] Failed to rename channel {self.channel_id}: {e}")

        # --- Update JSON persistence after sending / offline handling ---
        population_counts.append(total_players)
        if len(population_counts) > 60:
            population_counts = population_counts[-60:]
        last_monitor_timestamp = int(datetime.now().timestamp())

        # Save updated data
        with open(json_path, "w") as f:
            json.dump({
                "server_number": self.server_number,
                "last_timestamp": last_monitor_timestamp,
                "population_counts": population_counts,
                "last_channel_rename": last_channel_rename
            }, f)

        # --- Cleanup the graph file ---
        if graph_path:
            os.remove(graph_path)

        # --- Wait for the next update ---
        current_timestamp = int(datetime.now().timestamp())
        wait_time = (last_monitor_timestamp + 60) - current_timestamp
        if wait_time > 0:
            await asyncio.sleep(round(wait_time))


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
            # Use safe + normalized name here
            custom_server_name = self._normalize_server_name(self._safe_server_name(server_info))

            # Guard totals if matchmaking was odd
            try:
                total_players = int(total_players) if total_players is not None else 0
            except Exception:
                total_players = 0
            try:
                max_players = int(max_players) if max_players is not None else 0
            except Exception:
                max_players = 0
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




