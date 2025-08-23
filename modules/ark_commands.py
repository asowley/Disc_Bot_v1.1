# Ark server commands: /server and /list
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from tools.EOS import EOS
import aiohttp
import json
import logging
from discord.ui import View, Button
import datetime
from tools.database_tools import create_history_graph  # Import the function
import os

class ServerListView(View):
    def __init__(self, embeds):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.current = 0

        self.prev_button = Button(label="Previous", style=discord.ButtonStyle.secondary)
        self.next_button = Button(label="Next", style=discord.ButtonStyle.secondary)
        self.prev_button.callback = self.prev_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.update_buttons()

    async def prev_page(self, interaction: discord.Interaction):
        if self.current > 0:
            self.current -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def next_page(self, interaction: discord.Interaction):
        if self.current < len(self.embeds) - 1:
            self.current += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    def update_buttons(self):
        self.prev_button.disabled = self.current == 0
        self.next_button.disabled = self.current == len(self.embeds) - 1

class ArkCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="server", description="Show info about an ARK server by server number")
    @app_commands.describe(server_number="The ARK server number (e.g., 2000)")
    async def server(self, interaction: discord.Interaction, server_number: str):
        await interaction.response.defer(thinking=True)
        eos = EOS()
        max_retries = 3

        graph_path = None
        try:
            # Generate the graph with retries
            for attempt in range(max_retries):
                try:
                    logging.info(f"Generating graph for server {server_number} (attempt {attempt + 1})...")
                    graph_path = await asyncio.wait_for(create_history_graph(server_number, 2), timeout=10)
                    break
                except asyncio.TimeoutError:
                    logging.warning(f"Graph generation timed out for server {server_number} (attempt {attempt + 1}).")
                except Exception as e:
                    logging.error(f"Error generating graph for server {server_number} (attempt {attempt + 1}): {e}")
            else:
                logging.error(f"Failed to generate graph for server {server_number} after {max_retries} attempts.")

            # Fetch server info with retries
            result = None
            for attempt in range(max_retries):
                try:
                    logging.info(f"Fetching server info for {server_number} (attempt {attempt + 1})...")
                    result = await asyncio.wait_for(eos.matchmaking(server_number), timeout=10)
                    if result:
                        break
                except asyncio.TimeoutError:
                    logging.warning(f"Fetching server info timed out for {server_number} (attempt {attempt + 1}).")
                except Exception as e:
                    logging.error(f"Error fetching server info for {server_number} (attempt {attempt + 1}): {e}")
            else:
                await interaction.followup.send(f"Failed to fetch server info for `{server_number}` after {max_retries} attempts.", ephemeral=True)
                return

            server_info, total_players, max_players, ip_and_port = result

            # Prepare the embed
            custom_server_name = server_info['attributes'].get('CUSTOMSERVERNAME_s', 'Unknown')
            in_game_day = server_info['attributes'].get('DAYTIME_s', 'Unknown')
            player_count = server_info.get('totalPlayers', 'Unknown')
            ping = server_info['attributes'].get('EOSSERVERPING_l', 'Unknown')
            now = discord.utils.utcnow()

            embed = discord.Embed(
                title=f"Server Info",
                colour=discord.Colour.blue(),
                timestamp=now
            )
            embed.add_field(name="Server Name", value=f"```ansi\n{custom_server_name}```", inline=False)
            embed.add_field(name="In-game Day", value=f"```ansi\n{in_game_day}```", inline=False)
            embed.add_field(name="Player Count", value=f"```ansi\n{player_count}```", inline=True)
            embed.add_field(name="Ping", value=f"```ansi\n{ping}```", inline=True)
            embed.add_field(name="IP/Port", value=f"```ansi\n{ip_and_port}```", inline=False)

            # Attach the graph to the embed if it exists
            if graph_path:
                with open(graph_path, "rb") as f:
                    file_disc = discord.File(f, filename="image.png")
                    embed.set_image(url="attachment://image.png")
                    await interaction.followup.send(embed=embed, file=file_disc)
            else:
                await interaction.followup.send(embed=embed)

        except Exception as e:
            logging.error(f"Unexpected error in /server command: {e}")
            await interaction.followup.send(f"An unexpected error occurred while processing the server `{server_number}`.", ephemeral=True)
        finally:
            # Cleanup the graph file if it was created
            if graph_path:
                os.remove(graph_path)

    @app_commands.command(name="list", description="List ARK servers by population (e.g. /list 60 + for >=60 players)")
    @app_commands.describe(population="Population number", operator="Operator: + for >=, - for <=, = for exact")
    async def list(
        self,
        interaction: discord.Interaction,
        population: int,
        operator: str
    ):
        await interaction.response.defer(thinking=True)
        if operator not in ['+', '-', '=']:
            logging.warning(f"[ark_commands.py] Invalid operator used in /list: {operator}")
            await interaction.followup.send("Operator must be one of: +, -, =", ephemeral=True)
            return

        max_retries = 3
        servers = []
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                            "https://cdn2.arkdedicated.com/servers/asa/officialserverlist.json") as response:
                        data = await response.text()
                servers = json.loads(data)
                break
            except Exception as e:
                logging.error(f"[ark_commands.py] Failed to fetch server list (attempt {attempt+1}): {e}")
                await asyncio.sleep(2)

        if not servers:
            await interaction.followup.send("Failed to fetch server list after multiple attempts.", ephemeral=True)
            return

        servers_sorted = sorted(servers, key=lambda s: int(s.get('NumPlayers', 0)), reverse=True)

        embeds = []
        count = 0
        page_servers = []
        for server in servers_sorted:
            # Only include servers in the PVPCrossplay cluster and only PvP servers
            if server.get("ClusterId", "").upper() != "PVPCROSSPLAY":
                continue
            if server.get("SessionIsPve", 0) != 0:
                continue

            add_server = False
            num_players = int(server.get('NumPlayers', 0))
            if operator == '+':
                add_server = num_players >= population
            elif operator == '-':
                add_server = num_players <= population
            elif operator == '=':
                add_server = num_players == population

            if add_server:
                page_servers.append(server)
                count += 1

        if count == 0:
            embed = discord.Embed(
                title=f"ARK Servers with population {operator}{population}",
                description="No servers found matching your criteria.",
                colour=discord.Colour.green()
            )
            embeds.append(embed)
        else:
            # Split into pages of 12 for better readability with gaps
            for i in range(0, len(page_servers), 12):
                now = discord.utils.utcnow()
                embed = discord.Embed(
                    title=f"PVP SERVERS | POPULATION {operator} {population} (Page {i//12+1}/{(len(page_servers)-1)//12+1})",
                    colour=discord.Colour.green(),
                    timestamp=now
                )
                servers_on_page = page_servers[i:i+12]
                for server in servers_on_page:
                    num_players = int(server.get('NumPlayers', 0))
                    embed.add_field(
                        name=server.get('Name', 'Unknown'),
                        value=(
                            f"```Players: {num_players}\n"
                            f"Ping: {server.get('ServerPing', 'N/A')} | IP: {server.get('IP', 'N/A')}:{server.get('Port', 'N/A')}```"
                        ),
                        inline=False
                    )
                embeds.append(embed)

        view = ServerListView(embeds)
        await interaction.followup.send(embed=embeds[0], view=view)

async def setup(bot):
    await bot.add_cog(ArkCommands(bot))