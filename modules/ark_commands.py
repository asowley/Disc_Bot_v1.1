import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from tools.EOS import EOS
import aiohttp
import json
import logging
from discord.ui import View, Button

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
        retries = 0
        max_retries = 3
        server_info = None
        total_players = None
        max_players = None
        ip_and_port = None

        while retries < max_retries:
            try:
                result = await eos.matchmaking(server_number)
                if result is not None:
                    server_info, total_players, max_players, ip_and_port = result
                    break
            except Exception as e:
                pass
            retries += 1
            await asyncio.sleep(2)

        if server_info is None:
            await interaction.followup.send(f"Failed to retrieve info for server `{server_number}` after {max_retries} attempts.", ephemeral=True)
            return

        # Extract info
        server_name = server_info['attributes'].get('SESSIONNAME_s', 'Unknown')
        ping = server_info['attributes'].get('PING', 'Unknown')
        now = discord.utils.utcnow()
        timestamp = f"<t:{int(now.timestamp())}:F>"

        embed = discord.Embed(
            title=f"Server {server_number} Info",
            colour=discord.Colour.blue(),
            timestamp=now
        )
        embed.add_field(name="Server Name", value=server_name, inline=False)
        embed.add_field(name="Player Count", value=f"{total_players}/{max_players}", inline=False)
        embed.add_field(name="Ping", value=str(ping), inline=False)
        embed.add_field(name="IP:Port", value=ip_and_port, inline=False)
        embed.set_footer(text=f"Data as of {timestamp}")

        await interaction.followup.send(embed=embed)

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
            await interaction.followup.send("Operator must be one of: +, -, =", ephemeral=True)
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                        "https://cdn2.arkdedicated.com/servers/asa/officialserverlist.json") as response:
                    data = await response.text()
            servers = json.loads(data)
        except Exception as e:
            await interaction.followup.send("Failed to fetch server list.", ephemeral=True)
            return

        servers_sorted = sorted(servers, key=lambda s: int(s.get('NumPlayers', 0)), reverse=True)

        embeds = []
        count = 0
        page_servers = []
        for server in servers_sorted:
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
            # Split into pages of 25
            for i in range(0, len(page_servers), 25):
                embed = discord.Embed(
                    title=f"ARK Servers with population {operator}{population} (Page {i//25+1}/{(len(page_servers)-1)//25+1})",
                    colour=discord.Colour.green()
                )
                for server in page_servers[i:i+25]:
                    num_players = int(server.get('NumPlayers', 0))
                    embed.add_field(
                        name=server.get('Name', 'Unknown'),
                        value=f"Players: {num_players} | Ping: {server.get('ServerPing', 'N/A')} | IP: {server.get('Address', 'N/A')}",
                        inline=False
                    )
                embeds.append(embed)

        view = ServerListView(embeds)
        await interaction.followup.send(embed=embeds[0], view=view)

async def setup(bot):
    await bot.add_cog(ArkCommands(bot))