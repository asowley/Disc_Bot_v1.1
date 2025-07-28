import discord
from discord.ext import commands
import logging
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")  # Or set your token directly

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Load command modules
async def load_modules():
    await bot.load_extension("modules.ark_commands")
    await bot.load_extension("modules.eos_commands")
    # Add more modules here as needed

# Monitor manager code in place, but do not start monitors yet
from tools.Monitor_Manager import Monitor_Manager
monitor_manager = Monitor_Manager(bot)
# Do not call monitor_manager.start_monitors() yet

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await load_modules()
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} commands.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")
    logging.info("All modules loaded.")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler("bot.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    bot.run(TOKEN)