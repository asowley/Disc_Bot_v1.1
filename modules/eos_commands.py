import aiomysql
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from tools.EOS import EOS
from tools.player_display import build_player_list_embeds
from tools.connector import db_connector
import logging

class PlayerListView(discord.ui.View):
    def __init__(self, embeds):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.current = 0

        self.prev_button = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary)
        self.next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary)
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

class EOSCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="players", description="Show the players currently on an ARK server by server number")
    @app_commands.describe(server_number="The ARK server number (e.g., 2159)")
    async def players(self, interaction: discord.Interaction, server_number: str):
        await interaction.response.defer(thinking=True)
        eos = EOS()
        retries = 0
        max_retries = 3
        puids_info = []
        custom_server_name = ""
        total_players = 0
        max_players = 0

        try:
            # Get room_id from DB
            conn = await db_connector()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT room_id FROM ark_servers_new WHERE ark_server = %s", (server_number,)
                )
                row = await cursor.fetchone()
                room_id = row[0] if row else 0
            if room_id == 0:
                logging.warning(f"[eos_commands.py] No EOS ID found for server {server_number}.")
                await interaction.followup.send(f"No EOS ID found for server {server_number}.", ephemeral=True)
                return

            # Retry up to 3 times to get player info
            while retries < max_retries:
                try:
                    puids = await eos.players(server_number, room_id)
                    puids_info = await eos.info(puids)
                    server_info, total_players, max_players, _ = await eos.matchmaking(server_number)
                    custom_server_name = server_info["attributes"]["CUSTOMSERVERNAME_s"]
                    break
                except Exception as e:
                    logging.error(f"[eos_commands.py] Error fetching player info for server {server_number}: {e}")
                    retries += 1

            if not puids_info:
                logging.warning(f"[eos_commands.py] Failed to retrieve player info for server {server_number} after {max_retries} attempts.")
                await interaction.followup.send(f"Failed to retrieve player info for server `{server_number}` after {max_retries} attempts.", ephemeral=True)
                return

            embeds = await build_player_list_embeds(
                server_number, puids_info, custom_server_name, total_players, max_players, conn
            )

            view = PlayerListView(embeds)
            await interaction.followup.send(embed=embeds[0], view=view)

        except Exception as e:
            logging.error(f"[eos_commands.py] Unexpected error in /players: {e}")
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(
        name="player_info",
        description="Show info about a player by EOS ID, Steam64, Xbox Gamertag, or PSN ID"
    )
    @app_commands.describe(identifier="EOS ID, Steam64, Xbox Gamertag, or PSN ID")
    async def player_info(self, interaction: discord.Interaction, identifier: str):
        await interaction.response.defer(thinking=True)
        eos = EOS()
        puid = None
        max_retries = 3

        for attempt in range(max_retries):
            try:
                # Resolve EOS ID
                if identifier.startswith("0002"):
                    puid = identifier
                else:
                    conn = await db_connector()
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        await cursor.execute(
                            "SELECT puid FROM players WHERE account_id = %s", (identifier,)
                        )
                        row = await cursor.fetchone()
                        if row:
                            puid = row['puid']

                if not puid:
                    logging.warning(f"[eos_commands.py] Player not found in the database for identifier: {identifier}")
                    await interaction.followup.send("Player not found in the database.", ephemeral=True)
                    return

                # Get EOS info
                info = await eos.info([puid])
                if not info or len(info) == 0:
                    raise Exception("Player not found via EOS.")

                player_info = info[0]
                display_name = player_info.get("display_name", "Unknown")
                account_id = player_info.get("account", "Unknown")
                platform = player_info.get("platform", "Unknown")
                last_login = player_info.get("last_login", "Unknown")

                # Format display name as a clickable link to the appropriate profile site
                display_name_no_space = display_name.replace(" ", "%20")
                if platform == "xbl":
                    display_name_link = f"[{display_name}](https://xboxgamertag.com/search/{display_name_no_space})"
                elif platform == "psn":
                    display_name_link = f"[{display_name}](https://psnprofiles.com/{display_name_no_space})"
                else:
                    display_name_link = f"[{display_name}](https://steamcommunity.com/profiles/{account_id})"

                # Get alias and tribe/most joined server from database_tools
                conn = await db_connector()
                from tools.database_tools import get_user_alias, get_user_tribe_and_most_joined_server
                alias = await get_user_alias(puid, conn)
                tribe, most_joined_server = await get_user_tribe_and_most_joined_server(puid, conn)

                # Get recent join history (10 most recent)
                join_history_str = ""
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute("""
                        SELECT server_alias, timestamp 
                        FROM user_servers 
                        WHERE puid = %s 
                        ORDER BY timestamp DESC
                        LIMIT 10
                    """, (puid,))
                    data = await cursor.fetchall()
                    for row in data:
                        time_unix = int(row['timestamp'])
                        join_history_str += f"Joined **{row['server_alias']}** at <t:{time_unix}>\n"
                if not join_history_str:
                    join_history_str = "No recent join history found."

                embed = discord.Embed(
                    title=f"Player Info",
                    colour=discord.Colour.blue()
                )
                embed.add_field(name="EOS ID", value=puid, inline=False)
                embed.add_field(name="Account ID", value=account_id, inline=False)
                embed.add_field(name="Platform", value=platform, inline=False)
                embed.add_field(name="Display Name", value=display_name_link, inline=False)
                embed.add_field(name="Alias", value=alias, inline=False)
                embed.add_field(name="Tribe / Most Joined Server", value=f"{tribe} ({most_joined_server})", inline=False)
                embed.add_field(name="Last Login", value=last_login, inline=False)
                embed.add_field(name="Recent Joins", value=join_history_str, inline=False)

                await interaction.followup.send(embed=embed)
                return
            except Exception as e:
                logging.error(f"[eos_commands.py] Error in /player_info attempt {attempt+1} for identifier {identifier}: {e}")
                if attempt == max_retries - 1:
                    await interaction.followup.send(f"Error: {e}", ephemeral=True)
                else:
                    await asyncio.sleep(2)

async def setup(bot):
    await bot.add_cog(EOSCommands(bot))

