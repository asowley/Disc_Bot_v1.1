import asyncio
import json
import aiohttp
import random
import websockets
import logging

from connector import db_connector
import aiomysql


async def random_user():
    url = "https://cdn2.arkdedicated.com/asa/BanList.txt"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.text()

    data = data.split()
    return "LOGGER_Lethal"
    return data[random.randint(1, len(data) - 1)][:-2]  # Adjusted to avoid index out of range


class EOS:
    def __init__(self):
        self.client_secret = "eHl6YTc4OTFtdW9tUm15bklJSGFKQjlDT0JLa3dqNm46UFA1VUd4eXNFaWVOZlNyRWljYUQxTjJCYjNUZFh1RDd4SFljc2RVSFo3cw=="
        self.deployment_id = "ad9a8feffb3b4b2ca315546f038c3ae2"
        self.api_url = "https://api.epicgames.dev"

    async def get_token(self):
        url = self.api_url + "/auth/v1/oauth/token"

        payload = f"grant_type=client_credentials&deployment_id={self.deployment_id}"
        headers = {
            "Authorization": f"Basic {self.client_secret}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload, headers=headers) as response:
                token = await response.text()

        return json.loads(token)

    async def ticket(self, server):
        conn = await db_connector()

        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                SELECT room_id
                FROM ark_servers
                WHERE ark_server = %s
                AND room_id <> 0
            """, (server,))
            data = await cursor.fetchone()

        if data:
            room_id = data['room_id']
        else:
            return None, None, None

        url = f"{self.api_url}/rtc/v1/{self.deployment_id}/room/{room_id}"

        puid = await random_user()
        payload = {
            "participants": [
                {
                    "puid": f"{puid}",
                    "hardMuted": False
                }
            ]
        }

        token = await self.get_token()

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token['access_token']}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=json.dumps(payload), headers=headers) as response:
                data = await response.text()

        data = json.loads(data)

        return data['clientBaseUrl'], data['participants'][0]['token'], puid

    async def players(self, server):
        uri, ticket, puid = await self.ticket(server)

        first_message = {
            "type": "join",
            "ticket": ticket,
            "user_token": puid,
            "options": [
                "subscribe",
                "dtx",
                "rtcp_rsize",
                "new_audio_only_reasons",
                "v2",
                "unified_plan",
                "speaking",
                "reserved_audio_streams"
            ],
            "version": "1.16.2-32273396",
            "device": {
                "os": "Windows",
                "model": "",
                "manufacturer": "",
                "online_platform_type": "0"
            }
        }

        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps(first_message))
            response = await websocket.recv()
            await websocket.close()

            data = json.loads(response)

        users = []

        for user in data['users']:
            json_user = json.loads(user)

            puid = json_user['user_token']
            users.append(puid)

        return users

    async def info(self, uids):
        url = self.api_url + "/user/v9/product-users/search"

        payload = {"productUserIds": uids}

        token = await self.get_token()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token['access_token']}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=json.dumps(payload), headers=headers) as response:
                data = await response.text()

        data = json.loads(data)

        conn = await db_connector()

        players_info = []

        async with conn.cursor(aiomysql.DictCursor) as cursor:
            for users in data['productUsers'].items():
                puid = users[0]

                for account in users[1]['accounts']:
                    await cursor.execute("""
                        SELECT puid
                        FROM players
                        WHERE puid = %s
                        AND account_id = %s
                        AND provider = %s
                    """, (puid, account['accountId'], account['identityProviderId']))
                    existing_data = await cursor.fetchone()

                    if not existing_data:
                        await cursor.execute("""
                            INSERT INTO
                                players (puid, account_id, provider)
                            VALUES
                                (%s, %s, %s);
                        """, (puid, account['accountId'], account['identityProviderId']))
                        await conn.commit()

                    players_info.append({
                        "puid": puid,
                        "display_name": account['displayName'],
                        "account": account['accountId'],
                        "platform": account['identityProviderId']
                    })

        return players_info

    async def matchmaking(self, server_number):
        url = "https://cdn2.arkdedicated.com/servers/asa/officialserverlist.json"

        session_id = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logging.error(f"[EOS.py] Failed to fetch server data. HTTP status: {response.status}")
                        raise Exception(f"HTTP Fail {response.status}")
                    
                    data = await response.json()

                    if not isinstance(data, list):
                        logging.error("[EOS.py] Invalid data format from the server.")
                        raise Exception("Invalid Data ")
                        
                    server = next(
                        (
                            item
                            for item in data
                            if server_number in item.get("Name", "") and item.get("ClusterId") == "PVPCrossplay"
                        ),
                        None
                    )

                    if not server:
                        logging.error(f"[EOS.py] No server found with number {server_number} in the specified cluster.")
                        raise Exception(f"No server {server_number}")

                    session_id = server.get("SessionID", "N/A")
                    if session_id == "N/A":
                        logging.error(f"[EOS.py] No SessionID found for server {server_number}.")
                        raise Exception(f"No SessionID for server {server_number}")
        except Exception as e:
            logging.error(f"[EOS.py] EOS Matchmaking ERROR: {e}")
            return None  # Return None if error occurs
        
        url = f"{self.api_url}/matchmaking/v1/{self.deployment_id}/sessions/{session_id}"

        token = await self.get_token()

        headers = {
            "Authorization": f"Bearer {token['access_token']}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                data = await response.json()
                print(data)
        
        return data['publicData'], data['publicData']['totalPlayers'], data['publicData']['settings']['maxPublicPlayers']

# async def main():
#     eos = EOS()
#     result, total_players, max_players = await eos.matchmaking("2159")
#     print(result, total_players, max_players)

# if __name__ == "__main__":
#     asyncio.run(main())