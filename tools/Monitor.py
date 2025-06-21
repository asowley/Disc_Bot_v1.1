from datetime import datetime
import json
import logging
import os
import asyncio

import discord
from tools.EOS import EOS

from tools.connector import db_connector

class Monitor:
    '''\nA class to monitor a specific server and channel in a guild.\n
    server_number: The number of the server to monitor.\n
    type_of_monitor: The type of monitor (1 for server, 2 for channel).\n
    channel_id: The ID of the channel to send messages.\n
    guild_id: The ID of the guild where the channel is located.
    '''

    def __init__(self, server_number, type_of_monitor, channel_id, guild_id):
        self.server_number = server_number
        self.type_of_monitor = type_of_monitor
        self.channel_id = channel_id
        self.guild_id = guild_id

    async def start(self):
        '''\nStarts the monitor based on its type.\n'''

        logging.info(f"Starting monitor (type {self.type_of_monitor}) for server {self.server_number} in channel {self.channel_id} of guild {self.guild_id}")
        while True:
            if self.type_of_monitor == 1 or self.type_of_monitor == 2:
                self.run_monitor_type_1()
            elif self.type_of_monitor == 3:
                self.run_monitor_type_3()
            elif self.type_of_monitor == 4:
                self.run_monitor_type_4()
            else:
                logging.error(f"Unknown monitor type: {self.type_of_monitor}")

    async def run_monitor_type_1(self):
        '''\nA single monitor loop for monitors of type 1.\n'''

        eos = EOS()
        server_info, total_players, _ = await eos.matchmaking(self.server_number)

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

        # This is the player monitor
        try:
            puids = await eos.players(self.server_number)
            puids_info = await eos.info(puids)
            server_info, total_players, max_players = await eos.matchmaking(self.server_number)
            custom_server_name = server_info["attributes"]["CUSTOMSERVERNAME_s"]

        except Exception as e:
            logging.error(f"[Monitor.py] Error in run_monitor_type_2: {e}")
            return 
        embeds = []

        
        
    async def run_monitor_type_3(self):
        '''\nA single monitor loop for monitors of type 3.\n'''

        eos = EOS()
        server_info, total_players, max_players = await eos.matchmaking(self.server_number)

       


async def sort_player_info(puid, tribe):
    pass


