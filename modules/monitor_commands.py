import logging
import aiomysql
from discord import app_commands
from discord.ext import commands
from tools.connector import db_connector  # Adjust import if needed

class MonitorCommands(commands.Cog):
    def __init__(self, bot, monitor_manager):
        self.bot = bot
        self.monitor_manager = monitor_manager

    @app_commands.command(name="monitor", description="Add a monitor for an ARK server to this channel")
    @app_commands.describe(
        server_number="The ARK server number (required)",
        monitor_type="Monitor type (default: 1)",
        nickname="Optional nickname for this monitor",
        nature="Nature (default: 1)"
    )
    async def monitor(
        self,
        interaction,
        server_number: str,
        monitor_type: str = "1",
        nickname: str = "",
        nature: str = "1"
    ):
        await interaction.response.defer(thinking=True)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = await db_connector()
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Check if monitor already exists
                    await cursor.execute("""
                        SELECT 1 FROM monitors_new_upd
                        WHERE channel_id = %s AND type = %s AND ark_server = %s AND guild_id = %s AND nickname = %s AND nature = %s
                    """, (
                        interaction.channel_id,
                        monitor_type,
                        server_number,
                        interaction.guild_id,
                        nickname,
                        nature
                    ))
                    exists = await cursor.fetchone()
                    if exists:
                        await interaction.followup.send(
                            f"A monitor for server `{server_number}` with these settings already exists in this channel.",
                            ephemeral=True
                        )
                        return

                    # Insert new monitor
                    await cursor.execute("""
                        INSERT INTO monitors_new_upd (channel_id, type, ark_server, guild_id, nickname, nature)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        interaction.channel_id,
                        monitor_type,
                        server_number,
                        interaction.guild_id,
                        nickname,
                        nature
                    ))
                    await conn.commit()
                await interaction.followup.send(f"Monitor added for server `{server_number}` in this channel.", ephemeral=True)
                try:
                    await self.monitor_manager.add_monitor(
                        server_number,
                        monitor_type,
                        interaction.channel_id,
                        interaction.guild_id
                    )
                except Exception as e:
                    logging.error(f"[monitor_commands.py] Failed to start monitor after DB insert: {e}")
                return
            except Exception as e:
                logging.error(f"[monitor_commands.py] Error adding monitor (attempt {attempt+1}): {e}")
                if attempt == max_retries - 1:
                    await interaction.followup.send(f"Failed to add monitor: {e}", ephemeral=True)

    @app_commands.command(name="remove_monitor", description="Remove a monitor for an ARK server from this channel")
    @app_commands.describe(
        server_number="The ARK server number (required)", 
        type_of_monitor="Monitor type (default: 1)")
    async def remove_monitor(self, interaction, server_number: str, type_of_monitor: str = "1"):
        await interaction.response.defer(thinking=True)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                conn = await db_connector()
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute("""
                        DELETE FROM monitors_new_upd
                        WHERE channel_id = %s AND ark_server = %s AND guild_id = %s AND type = %s
                    """, (
                        interaction.channel_id,
                        server_number,
                        interaction.guild_id,
                        type_of_monitor
                    ))
                    await conn.commit()
                try:
                    await self.monitor_manager.remove_monitor(
                        server_number,
                        type_of_monitor,
                        interaction.channel_id,
                        interaction.guild_id
                    )
                except Exception as e:
                    logging.error(f"[monitor_commands.py] Failed to stop monitor after DB delete: {e}")
                await interaction.followup.send(f"Monitor removed for server `{server_number}` from this channel.", ephemeral=True)
                return
            except Exception as e:
                logging.error(f"[monitor_commands.py] Error removing monitor (attempt {attempt+1}): {e}")
                if attempt == max_retries - 1:
                    await interaction.followup.send(f"Failed to remove monitor: {e}", ephemeral=True)

    # Add Alert Command
    @app_commands.command(name="add_alert", description="Add an alert to an existing monitor.")
    @app_commands.describe(
        server_number="The ARK server number to monitor.",
        population_change_threshold="The population change required to trigger the alert. Negative for players left, Positive for players joined."
    )
    async def add_alert(self, interaction, server_number: int, population_change_threshold: int):
        """
        Add an alert to an existing monitor.
        """
        guild_id = interaction.guild_id  # Get the guild ID from the interaction
        alert_channel_id = interaction.channel_id  # Use the channel where the command was invoked

        success = await self.monitor_manager.add_alert_to_monitor(
            server_number=server_number,
            guild_id=guild_id,
            alert_channel_id=alert_channel_id,
            population_change_threshold=population_change_threshold
        )

        if success:
            await interaction.response.send_message(
                f"Alert added successfully for server `{server_number}` in this channel.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Failed to add alert. No monitor of type 1 found for server `{server_number}` in this guild. Add a type 1 monitor before setting an alert",
                ephemeral=True
            )

    # Remove Alert Command
    @app_commands.command(name="remove_alert", description="Remove an alert from an existing monitor.")
    @app_commands.describe(
        server_number="The ARK server number to monitor."
    )
    async def remove_alert(self, interaction, server_number: int):
        """
        Remove an alert from an existing monitor.
        """
        guild_id = interaction.guild_id  # Get the guild ID from the interaction
        success = await self.monitor_manager.remove_alert_from_monitor(
            server_number=server_number,
            guild_id=guild_id
        )

        if success:
            await interaction.response.send_message(
                f"Alert removed successfully for server `{server_number}` in this guild.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Failed to remove alert. No monitor of type 1 found for server `{server_number}` in this guild.",
                ephemeral=True
            )

async def setup(bot):
    from tools.Monitor_Manager import monitor_manager  # Or pass as argument if needed
    await bot.add_cog(MonitorCommands(bot, monitor_manager))