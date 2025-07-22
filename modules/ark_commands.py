import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from tools.EOS import EOS

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

async def setup(bot):
    await bot.add_cog(ArkCommands(bot))