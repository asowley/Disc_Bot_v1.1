from datetime import datetime, timezone
import json
import logging
import os
import asyncio
import aiomysql

import discord
from tools.EOS import EOS
from tools.database_tools import get_user_alias, get_user_tribe_and_most_joined_server

from tools.connector import db_connector

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
        self.type_of_monitor = type_of_monitor
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
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                self.stopped = True
                pass

    async def _run_with_restart(self):
        # Internal: run the monitor, restart if cancelled
        while True:
            try:
                await self._run_monitor()
            except asyncio.CancelledError:
                # If cancelled, break the loop to stop
                if self.stopped:
                    logging.info(f"Monitor for server {self.server_number} has been stopped.")
                    break
                await asyncio.sleep(10)  # Wait before restart
            except Exception as e:
                logging.error(f"Monitor crashed with error: {e}, restarting...")
                await asyncio.sleep(10)  # Wait before restart

    async def _run_monitor(self):
        logging.info(f"Starting monitor (type {self.type_of_monitor}) for server {self.server_number} in channel {self.channel_id} of guild {self.guild_id}")
        if self.type_of_monitor == 1 or self.type_of_monitor == 2:
            await self.run_monitor_type_1()
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
            # You may want to send this embed to the channel here

        # --- Channel rename logic ---
        now_ts = int(datetime.now().timestamp())
        channel_rename_interval = 5 * 60  # 5 minutes in seconds

        if now_ts - last_channel_rename >= channel_rename_interval:
            try:
                # Fetch the channel object (requires bot instance)
                guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
                if guild:
                    channel = guild.get_channel(self.channel_id)
                    if channel:
                        new_name = f"{server_info['attributes']['SESSIONNAME_s']}-{total_players}"
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
        ''' \nA single monitor loop for monitors of type 2.\n'''

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
            return

        # Fetch user aliases for all puids in one query for efficiency
        puid_list = [player['puid'] for player in puids_info]
        puid_to_alias = {}

        if puid_list:
            # Use get_user_alias for each puid, passing the same conn for efficiency
            for puid in puid_list:
                puid_to_alias[puid] = await get_user_alias(puid, conn)

        # Fetch tribe for each player using the smart SQL
        puid_to_tribe = {}
        for puid in puid_list:
            tribe, server_alias = await get_user_tribe_and_most_joined_server(puid, conn)
            if tribe and tribe != "Unknown":
                puid_to_tribe[puid] = f"{tribe} ({server_alias})"
            elif server_alias:
                puid_to_tribe[puid] = f"{server_alias}"
            else:
                puid_to_tribe[puid] = "Unknown"

        # Build player lines, coloring the line green if the player's main server matches this monitor's server_number, else red
        player_lines = []
        for idx, player in enumerate(puids_info, 1):
            alias = puid_to_alias.get(player['puid'], "Unknown")
            tribe = puid_to_tribe.get(player['puid'], "Unknown")
            # Extract the main server number from the tribe string (format: "TribeName (server_number)" or just "server_number")
            main_server = None
            if "(" in tribe and ")" in tribe:
                try:
                    main_server = tribe.split("(")[-1].replace(")", "").strip()
                except Exception:
                    main_server = None
            elif tribe.isdigit():
                main_server = tribe

            # Use ANSI color codes for code block (Discord will show as plain text, but some clients may parse)
            line_content = f"[{idx:02d}] | {player['display_name']:<20} ({alias:<15}) | {tribe:<20} | {player['last_login']}"
            if str(main_server) == str(self.server_number):
                # Green
                line = f"\u001b[1;32m{line_content}\u001b[0m"
            else:
                # Red
                line = f"\u001b[1;31m{line_content}\u001b[0m"
            player_lines.append(line)

        # Count players by main server
        server_counts = {}
        for idx, player in enumerate(puids_info, 1):
            tribe = puid_to_tribe.get(player['puid'], "Unknown")
            main_server = None
            if "(" in tribe and ")" in tribe:
                try:
                    main_server = tribe.split("(")[-1].replace(")", "").strip()
                except Exception:
                    main_server = None
            elif tribe.isdigit():
                main_server = tribe
            if main_server:
                server_counts[main_server] = server_counts.get(main_server, 0) + 1

        # Split lines into embeds, each with description <= 3700 chars, using code block for alignment
        embeds = []
        desc = "```"
        for i, line in enumerate(player_lines):
            if len(desc) + len(line) + 1 > 3690:  # leave room for closing ```
                desc += "```"
                embed = discord.Embed(
                    title=f"Players on {custom_server_name} ({total_players}/{max_players})",
                    description=desc,
                    colour=discord.Colour.green()
                )
                embeds.append(embed)
                desc = "```"
            desc += line + "\n"
        desc += "```"

        # Add server counts summary to the last embed
        if server_counts:
            summary = "------------------\n"
            for server, count in sorted(server_counts.items(), key=lambda x: int(x[0])):
                summary += f"{server}: {count}\n"
            desc += summary

        # Calculate Discord timestamp for "updated X ago"
        now = datetime.now(timezone.utc)
        discord_timestamp = f"<t:{int(now.timestamp())}:R>"

        if desc.strip("` \n"):
            # Add "updated X ago" to the title of the first embed
            first_title = f"Players on {custom_server_name} ({total_players}/{max_players}) • updated {discord_timestamp}"
            embed = discord.Embed(
                title=first_title,
                description=desc,
                colour=discord.Colour.green()
            )
            embeds.append(embed)

        # Purge previous messages before sending new embeds
        guild = discord.utils.get(self.bot.guilds, id=self.guild_id)
        if guild:
            channel = guild.get_channel(self.channel_id)
            if channel:
                # Purge the last 5 messages from anyone in the channel
                try:
                    await channel.purge(limit=5)
                except Exception as e:
                    logging.error(f"[Monitor.py] Failed to purge messages: {e}")
                # Send all embeds to the channel
                for embed in embeds:
                    await channel.send(embed=embed)

    async def run_monitor_type_3(self):
        '''\nA single monitor loop for monitors of type 3.\n'''

        eos = EOS()
        server_info, total_players, max_players, ip_and_port = await eos.matchmaking(self.server_number)

       


async def sort_player_info(puid, tribe):
    pass


