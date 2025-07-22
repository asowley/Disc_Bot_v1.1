import discord
from datetime import datetime, timezone
from tools.database_tools import get_user_alias, get_user_tribe_and_most_joined_server

async def build_player_list_embeds(server_number, puids_info, custom_server_name, total_players, max_players, conn):
    # Fetch user aliases and tribes efficiently
    puid_list = [player['puid'] for player in puids_info]
    puid_to_alias = {}
    puid_to_tribe = {}

    if puid_list:
        for puid in puid_list:
            puid_to_alias[puid] = await get_user_alias(puid, conn)
            tribe, server_alias = await get_user_tribe_and_most_joined_server(puid, conn)
            if tribe and tribe != "Unknown":
                puid_to_tribe[puid] = f"{tribe} ({server_alias})"
            elif server_alias:
                puid_to_tribe[puid] = f"{server_alias}"
            else:
                puid_to_tribe[puid] = "Unknown"

    # Build player lines with ANSI color codes
    player_lines = []
    for idx, player in enumerate(puids_info, 1):
        alias = puid_to_alias.get(player['puid'], "Unknown")
        tribe = puid_to_tribe.get(player['puid'], "Unknown")
        main_server = None
        if "(" in tribe and ")" in tribe:
            try:
                main_server = tribe.split("(")[-1].replace(")", "").strip()
            except Exception:
                main_server = None
        elif tribe.isdigit():
            main_server = tribe

        line_content = f"[{idx:02d}] | {player['display_name']:<20} ({alias:<15}) | {tribe:<20} | {player['last_login']}"
        if str(main_server) == str(server_number):
            line = f"\u001b[1;32m{line_content}\u001b[0m"
        else:
            line = f"\u001b[1;31m{line_content}\u001b[0m"
        player_lines.append(line)

    # Count players by main server
    server_counts = {}
    for player in puids_info:
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

    return embeds