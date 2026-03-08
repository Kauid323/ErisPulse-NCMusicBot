import os
import json
import asyncio
import aiohttp
import re
from typing import Dict, Any, List
from datetime import datetime

from ErisPulse import sdk
from ErisPulse.Core.Bases import BaseModule
from ErisPulse.Core.Event import message, notice, request

# Search API
# Search API
SEARCH_API = "http://localhost:3000/search"
SONG_URL_API = "http://localhost:3000/song/url/v1"
SONG_DETAIL_API = "http://localhost:3000/song/detail"
COMMENT_MUSIC_API = "http://localhost:3000/comment/music"
PLAYLIST_DETAIL_API = "http://localhost:3000/playlist/detail"
PLAYLIST_TRACK_ALL_API = "http://localhost:3000/playlist/track/all"

class Main(BaseModule):
    # User session state: user_id -> { "songs": [...], "state": "selecting" }
    user_sessions: Dict[str, Dict[str, Any]] = {}
    _session_counter: int = 0

    @staticmethod
    def _session_key(event: Dict[str, Any], user_id: str) -> str:
        platform = event.get("platform") or "yunhu"
        detail_type = "group" if event.get("group_id") else "user"
        target_id = event.get("group_id") or user_id
        return f"{platform}:{detail_type}:{target_id}:{user_id}"

    async def _cancel_session(self, session_key: str):
        session = Main.user_sessions.pop(session_key, None)
        if not session:
            return

    def _schedule_session_timeout(self, session_key: str, session_id: int, timeout_s: float = 3000.0):
        return None

    async def on_load(self, event) -> bool:
        sdk.logger.info(f"MusicBot module loaded from: {__file__}")
        # Register for message events to catch commands
        sdk.adapter.on("message")(self.handle_any_event)
        sdk.adapter.on("message")(self.handle_message)
        return True

    @staticmethod
    def should_eager_load() -> bool:
        return True

    @staticmethod
    async def get_search_results(keywords: str, limit: int = 30, offset: int = 0) -> List[Dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(SEARCH_API, params={"keywords": keywords, "limit": limit, "offset": offset}) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                # Adapting to the structure in netease-api-req.txt
                # { "result": { "songs": [ ... ] }, "code": 200 }
                if data.get("code") == 200 and "result" in data and "songs" in data["result"]:
                    return data["result"]["songs"]
                return []

    @staticmethod
    async def get_playlist_search_results(keywords: str, limit: int = 30, offset: int = 0) -> List[Dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                SEARCH_API,
                params={"keywords": keywords, "limit": limit, "offset": offset, "type": 1000},
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                if data.get("code") == 200 and "result" in data and "playlists" in data["result"]:
                    return data["result"]["playlists"]
                return []

    @staticmethod
    async def get_playlist_detail(playlist_id: int) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(PLAYLIST_DETAIL_API, params={"id": playlist_id}) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                if data.get("code") == 200 and isinstance(data.get("playlist"), dict):
                    return data["playlist"]
                return {}

    @staticmethod
    async def get_playlist_tracks(playlist_id: int, limit: int = 30, offset: int = 0) -> List[Dict[str, Any]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                PLAYLIST_TRACK_ALL_API,
                params={"id": playlist_id, "limit": limit, "offset": offset},
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                songs = data.get("songs")
                if isinstance(songs, list):
                    return songs
                return []

    @staticmethod
    async def get_song_url(song_id: int) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(SONG_URL_API, params={"id": song_id, "level": "exhigh"}) as resp:
                if resp.status != 200:
                    sdk.logger.error(f"API Error: {resp.status}")
                    return None
                data = await resp.json()
                # Structure: { "data": [ { "url": "..." } ] }
                if data.get("code") == 200 and "data" in data and len(data["data"]) > 0:
                    return data["data"][0].get("url")
                return None

    @staticmethod
    async def get_song_detail(song_id: int) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.get(SONG_DETAIL_API, params={"ids": song_id}) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                if data.get("code") == 200 and data.get("songs"):
                    return data["songs"][0]
                return {}

    @staticmethod
    async def get_comment_total(song_id: int) -> int:
        async with aiohttp.ClientSession() as session:
            async with session.get(COMMENT_MUSIC_API, params={"id": song_id, "limit": 1}) as resp:
                if resp.status != 200:
                    return 0
                data = await resp.json()
                total = data.get("total")
                if isinstance(total, int):
                    return total
                return 0

    @staticmethod
    async def generate_video_from_audio(audio_path: str, output_path: str, duration: int):
        # 1080x720 video
        try:
            # Check audio file size
            if os.path.exists(audio_path):
                size = os.path.getsize(audio_path)
                sdk.logger.info(f"Audio file size: {size} bytes")
                if size == 0:
                    raise Exception("Audio file is empty")
            else:
                 raise Exception("Audio file not found")

            # Calculate duration in seconds
            duration_sec = str(duration / 1000.0)
            
            # Construct FFmpeg command
            # ffmpeg -f lavfi -i color=c=black:s=1080x720:r=5 -t <duration> -i <audio> -c:v libx264 -c:a aac -pix_fmt yuv420p -shortest <output> -y
            args = [
                "ffmpeg",
                "-f", "lavfi",
                "-i", "color=c=black:s=540x280:r=5",
                "-t", duration_sec,
                "-i", audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "libx264",
                "-c:a", "aac",
                "-pix_fmt", "yuv420p",
                "-shortest",
                output_path,
                "-y"
            ]
            
            sdk.logger.info(f"Running FFmpeg command: {' '.join(args)}")
            
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else 'Unknown Error'
                sdk.logger.error(f"FFmpeg failed with return code {process.returncode}: {error_msg}")
                raise Exception(f"FFmpeg failed: {error_msg}")

            if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
                # 50 bytes is definitely too small for a video
                sdk.logger.error(f"Generated video is too small or missing. Stderr: {stderr.decode() if stderr else ''}")
                raise Exception("Generated video is invalid (file too small)")
                
            sdk.logger.info("Video generation successful")
            
        except FileNotFoundError:
             sdk.logger.error("FFmpeg executable not found. Please verify valid ffmpeg installation and ensure it is in your PATH.")
             raise Exception("FFmpeg executable not found")
        except Exception as e:
            sdk.logger.error(f"Video generation error: {e}")
            raise e

    async def handle_message(self, event: Dict[str, Any]):
        try:
            user_id = event.get("user_id")
            message_text = ""
            
            # Extract text from message chain/segments
            if "message" in event and isinstance(event["message"], list):
                for seg in event["message"]:
                    if seg.get("type") == "text":
                        message_text += seg.get("data", {}).get("text", "")
            elif "raw_message" in event:
                message_text = event["raw_message"]

            if not user_id or not message_text:
                return

            # Check if user is in selecting state
            session_key = Main._session_key(event, user_id)
            if session_key in Main.user_sessions:
                session = Main.user_sessions[session_key]
                msg = message_text.strip()

                state = session.get("state")
                mode = session.get("mode", "song")

                if state == "playlist_confirm_tracks":
                    if msg.upper() == "Y":
                        playlist_id = session.get("playlist_id")
                        if not playlist_id:
                            return

                        limit = int(session.get("limit", 30))
                        page = 1
                        offset = 0
                        songs = await self.get_playlist_tracks(int(playlist_id), limit=limit, offset=offset)

                        playlist_name = session.get("playlist_name", "")
                        reply_msg = f"歌单：{playlist_name}\n共有 {len(songs)} 条结果，请输入数字来获取歌曲\n"
                        for idx, song in enumerate(songs):
                            song_name = song.get("name", "Unknown")
                            artists = song.get("artists") or song.get("ar") or song.get("artist") or []
                            artist_names = "/".join([a.get("name", "") for a in artists if isinstance(a, dict)])
                            line = f"{idx + 1}. {song_name} - {artist_names}"
                            reply_msg += f"{line}\n"
                        reply_msg += "\n发送'列表 N'（N为阿拉伯数字）来获取更多结果"

                        adapter_instance = getattr(sdk.adapter, session.get("platform", "yunhu"), sdk.adapter.yunhu)
                        if adapter_instance:
                            await adapter_instance.Send.To(session.get("detail_type", "user"), session.get("target_id")).Text(reply_msg)

                        session["songs"] = songs
                        session["state"] = "selecting"
                        session["mode"] = "playlist_tracks"
                        session["page"] = page
                        return

                    if msg.upper() == "N":
                        asyncio.create_task(self._cancel_session(session_key))
                        return
                m = re.match(r"^列表\s*(\d+)$", msg)
                if m:
                    page = int(m.group(1))
                    if page < 1:
                        return

                    keywords = session.get("keywords")
                    limit = int(session.get("limit", 10))
                    offset = (page - 1) * limit
                    if mode == "playlist":
                        if not keywords:
                            return

                        playlists = await self.get_playlist_search_results(keywords, limit=limit, offset=offset)
                        reply_msg = f"共有 {len(playlists)} 条结果，请输入数字来获取歌单\n"
                        for idx, pl in enumerate(playlists):
                            pl_name = pl.get("name", "Unknown")
                            creator = pl.get("creator") or {}
                            nickname = creator.get("nickname", "") if isinstance(creator, dict) else ""
                            track_count = pl.get("trackCount")
                            track_count_str = str(track_count) if isinstance(track_count, int) else ""
                            line = f"{idx + 1}. {pl_name} - {nickname} {track_count_str}".strip()
                            reply_msg += f"{line}\n"
                        reply_msg += "\n发送'列表 N'（N为阿拉伯数字）来获取更多结果"

                        adapter_instance = getattr(sdk.adapter, session.get("platform", "yunhu"), sdk.adapter.yunhu)
                        if adapter_instance:
                            await adapter_instance.Send.To(session.get("detail_type", "user"), session.get("target_id")).Text(reply_msg)

                        session["playlists"] = playlists
                        session["page"] = page
                        return

                    if mode == "playlist_tracks":
                        playlist_id = session.get("playlist_id")
                        if not playlist_id:
                            return
                        songs = await self.get_playlist_tracks(int(playlist_id), limit=limit, offset=offset)
                        playlist_name = session.get("playlist_name", "")
                        reply_msg = f"歌单：{playlist_name}\n共有 {len(songs)} 条结果，请输入数字来获取歌曲\n"
                        for idx, song in enumerate(songs):
                            song_name = song.get("name", "Unknown")
                            artists = song.get("artists") or song.get("ar") or song.get("artist") or []
                            artist_names = "/".join([a.get("name", "") for a in artists if isinstance(a, dict)])
                            line = f"{idx + 1}. {song_name} - {artist_names}"
                            reply_msg += f"{line}\n"
                        reply_msg += "\n发送'列表 N'（N为阿拉伯数字）来获取更多结果"

                        adapter_instance = getattr(sdk.adapter, session.get("platform", "yunhu"), sdk.adapter.yunhu)
                        if adapter_instance:
                            await adapter_instance.Send.To(session.get("detail_type", "user"), session.get("target_id")).Text(reply_msg)

                        session["songs"] = songs
                        session["page"] = page
                        return

                    # default: song mode
                    if not keywords:
                        return

                    songs = await self.get_search_results(keywords, limit=limit, offset=offset)
                    reply_msg = f"共有 {len(songs)} 条结果，请输入数字来获取歌曲\n"
                    for idx, song in enumerate(songs):
                        song_name = song.get("name", "Unknown")
                        artists = song.get("artists") or song.get("ar") or song.get("artist") or []
                        artist_names = "/".join([a.get("name", "") for a in artists if isinstance(a, dict)])
                        line = f"{idx + 1}. {song_name} - {artist_names}"
                        reply_msg += f"{line}\n"
                    reply_msg += "\n发送'列表 N'（N为阿拉伯数字）来获取更多结果"

                    adapter_instance = getattr(sdk.adapter, session.get("platform", "yunhu"), sdk.adapter.yunhu)
                    if adapter_instance:
                        await adapter_instance.Send.To(session.get("detail_type", "user"), session.get("target_id")).Text(reply_msg)

                    session["songs"] = songs
                    session["page"] = page
                    return

                if msg.isdigit():
                    choice = int(msg)
                    if mode == "playlist":
                        playlists = session.get("playlists") or []
                        if 1 <= choice <= len(playlists):
                            selected = playlists[choice - 1]
                            playlist_id = selected.get("id")
                            if not playlist_id:
                                return

                            detail = await self.get_playlist_detail(int(playlist_id))

                            name = detail.get("name") or selected.get("name") or ""
                            creator = detail.get("creator") or selected.get("creator") or {}
                            nickname = creator.get("nickname", "") if isinstance(creator, dict) else ""
                            creator_id = creator.get("userId") if isinstance(creator, dict) else ""
                            create_time = detail.get("createTime")
                            try:
                                create_time_str = datetime.fromtimestamp(int(create_time) / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
                            except Exception:
                                create_time_str = ""
                            cover_url = detail.get("coverImgUrl") or selected.get("coverImgUrl") or ""

                            md = (
                                f"歌单id：{playlist_id}\n\n"
                                f"歌单名称：{name}\n\n"
                                f"创建时间：{create_time_str}\n\n"
                                f"创建用户：{nickname}\n\n"
                                f"用户id：{creator_id}\n\n"
                                f"歌单封面：\n\n"
                                f"![]({cover_url})\n\n"
                                f"是否要查看歌单内歌曲？（Y/N）"
                            )

                            adapter_instance = getattr(sdk.adapter, session.get("platform", "yunhu"), sdk.adapter.yunhu)
                            if adapter_instance and hasattr(adapter_instance.Send.To(session.get("detail_type", "user"), session.get("target_id")), "Markdown"):
                                await adapter_instance.Send.To(session.get("detail_type", "user"), session.get("target_id")).Markdown(md)
                            elif adapter_instance:
                                await adapter_instance.Send.To(session.get("detail_type", "user"), session.get("target_id")).Text(md)

                            session["state"] = "playlist_confirm_tracks"
                            session["playlist_id"] = int(playlist_id)
                            session["playlist_name"] = name
                            return
                        return

                    songs = session.get("songs", [])
                    if 1 <= choice <= len(songs):
                        selected_song = songs[choice - 1]
                        asyncio.create_task(self.process_selection(event, selected_song, session))
                        asyncio.create_task(self._cancel_session(session_key))
                    else:
                        pass
        except Exception as e:
             sdk.logger.error(f"Error in handle_message: {e}")

    # Listen for the specific command webhook/event
    # Since the exact event type for "webhook command 2241" is platform specific and likely passed through 
    # ErisPulse as a raw event or a specific message type, we'll try to catch it via a global event listener
    # and check the command ID.
    async def handle_any_event(self, event: Dict[str, Any]):
        # Check for Yunhu specific command structure
        if "yunhu_command" in event:
            sdk.logger.info(f"Received Yunhu command event: {event.get('yunhu_command')}")
            cmd = event["yunhu_command"]
            if str(cmd.get("id")) == "2241":
                await self.process_command_2241(event)
                return
            if str(cmd.get("id")) == "2269":
                await self.process_command_2269(event)
                return

        # Fallback to previous checks
        try:
            data = event.get("data", {})
            raw_event = data if isinstance(data, dict) else event
            
            # Common patterns for command events
            cid = raw_event.get("command_id") or raw_event.get("commandId")
            
            # If not in top level, check 'data' subfield if it exists
            if not cid and "data" in raw_event and isinstance(raw_event["data"], dict):
                cid = raw_event["data"].get("command_id") or raw_event["data"].get("commandId")

            if str(cid) == "2241":
                await self.process_command_2241(raw_event)
            if str(cid) == "2269":
                await self.process_command_2269(raw_event)
        except Exception as e:
            # Don't log spam for every event
            pass

    async def process_command_2269(self, event):
        user_id = event.get("user_id") or event.get("sender", {}).get("user_id")

        keywords = ""
        if "yunhu_command" in event:
            keywords = event["yunhu_command"].get("args", "")

        if not keywords:
            if "message" in event:
                if isinstance(event["message"], str):
                    keywords = event["message"]
                elif isinstance(event["message"], list):
                    for seg in event["message"]:
                        if seg.get("type") == "text":
                            keywords += seg.get("data", {}).get("text", "")

        if not keywords and "params" in event:
            keywords = event["params"]

        if not keywords:
            keywords = event.get("raw_message", "")

        sdk.logger.info(f"Received playlist search command for: {keywords}")

        limit = 30
        page = 1
        playlists = await self.get_playlist_search_results(keywords, limit=limit, offset=0)

        reply_msg = f"共有 {len(playlists)} 条结果，请输入数字来获取歌单\n"
        for idx, pl in enumerate(playlists):
            pl_name = pl.get("name", "Unknown")
            creator = pl.get("creator") or {}
            nickname = creator.get("nickname", "") if isinstance(creator, dict) else ""
            track_count = pl.get("trackCount")
            track_count_str = str(track_count) if isinstance(track_count, int) else ""
            line = f"{idx + 1}. {pl_name} - {nickname} {track_count_str}".strip()
            reply_msg += f"{line}\n"
        reply_msg += "\n发送'列表 N'（N为阿拉伯数字）来获取更多结果"

        platform = "yunhu"
        if "platform" in event:
            platform = event["platform"]

        adapter_instance = getattr(sdk.adapter, platform, None)
        if not adapter_instance:
            adapter_instance = sdk.adapter.yunhu

        detail_type = "user"
        target_id = user_id
        if "group_id" in event and event["group_id"]:
            detail_type = "group"
            target_id = event["group_id"]

        if adapter_instance:
            await adapter_instance.Send.To(detail_type, target_id).Text(reply_msg)

        session_key = Main._session_key({"platform": platform, "group_id": event.get("group_id")}, user_id)
        await self._cancel_session(session_key)

        Main.user_sessions[session_key] = {
            "playlists": playlists,
            "state": "selecting",
            "mode": "playlist",
            "keywords": keywords,
            "limit": limit,
            "page": page,
            "platform": platform,
            "detail_type": detail_type,
            "target_id": target_id,
        }

    async def process_command_2241(self, event):
        user_id = event.get("user_id") or event.get("sender", {}).get("user_id")
        
        keywords = ""
        # Prefer Yunhu command args if available
        if "yunhu_command" in event:
            keywords = event["yunhu_command"].get("args", "")
        
        # Fallback extraction logic
        if not keywords:
            if "message" in event:
                 if isinstance(event["message"], str):
                     keywords = event["message"]
                 elif isinstance(event["message"], list):
                     for seg in event["message"]:
                         if seg.get("type") == "text":
                             keywords += seg.get("data", {}).get("text", "")
        
        # Fallback if empty, maybe it's in a specific field for slash commands
        if not keywords and "params" in event:
             keywords = event["params"]

        if not keywords:
            # Try getting from raw command text if simple message
            keywords = event.get("raw_message", "")

        sdk.logger.info(f"Received search command for: {keywords}")

        limit = 30
        page = 1
        songs = await self.get_search_results(keywords, limit=limit, offset=0)
        
        reply_msg = f"共有 {len(songs)} 条结果，请输入数字来获取歌曲\n"
        for idx, song in enumerate(songs):
            song_name = song.get("name", "Unknown")
            # Artist Handling
            artists = song.get("artists") or song.get("ar") or song.get("artist") or []
            artist_names = "/".join([a.get("name", "") for a in artists])
            
            line = f"{idx + 1}. {song_name} - {artist_names}"
            reply_msg += f"{line}\n"

        reply_msg += "\n发送'列表 N'（N为阿拉伯数字）来获取更多结果"

        # Send response
        platform = "yunhu" # Triggered by Yunhu command 2241 likely
        # But we should use the platform from event if available
        if "platform" in event:
            platform = event["platform"]
            
        adapter_instance = getattr(sdk.adapter, platform, None)
        # Fallback to yunhu if not found (since config has yunhu)
        if not adapter_instance:
             adapter_instance = sdk.adapter.yunhu

        # Determine target type and id
        detail_type = "user"
        target_id = user_id
        if "group_id" in event and event["group_id"]:
            detail_type = "group"
            target_id = event["group_id"]
        
        if adapter_instance:
            await adapter_instance.Send.To(detail_type, target_id).Text(reply_msg)

        # Save state (scoped by platform + conversation + user)
        session_key = Main._session_key({"platform": platform, "group_id": event.get("group_id")}, user_id)
        await self._cancel_session(session_key)

        Main.user_sessions[session_key] = {
            "songs": songs,
            "state": "selecting",
            "keywords": keywords,
            "limit": limit,
            "page": page,
            "platform": platform,
            "detail_type": detail_type,
            "target_id": target_id,
        }

    async def process_selection(self, event, song, session_context=None):
        song_id = song.get("id")
        duration = song.get("duration", 0)
        
        # Resolve context
        user_id = event.get("user_id")
        if session_context is None:
             session_key = Main._session_key(event, user_id)
             session_context = Main.user_sessions.get(session_key, {})
             
        platform = session_context.get("platform", "yunhu")
        detail_type = session_context.get("detail_type", "user")
        target_id = session_context.get("target_id", user_id)
        
        adapter_instance = getattr(sdk.adapter, platform, sdk.adapter.yunhu)

        try:
            detail = await self.get_song_detail(song_id)
            comment_total = await self.get_comment_total(song_id)

            name = detail.get("name") or song.get("name") or ""
            main_title = detail.get("mainTitle") or ""

            artists = detail.get("ar") or detail.get("artists") or song.get("artists") or song.get("ar") or []
            artist_names = "/ ".join([a.get("name", "") for a in artists if isinstance(a, dict)])

            album = detail.get("al") or detail.get("album") or {}
            album_name = album.get("name", "") if isinstance(album, dict) else ""
            cover_url = album.get("picUrl", "") if isinstance(album, dict) else ""

            pop = detail.get("pop")
            pop_str = str(int(pop)) if isinstance(pop, (int, float)) else ""

            md = (
                f"歌名：{name}\n\n"
                f"主标题：{main_title}\n\n"
                f"歌手：{artist_names}\n\n"
                f"所属专辑：{album_name}\n\n"
                f"歌曲热度：{pop_str}\n\n"
                f"评论 {comment_total}\n\n"
                f"歌曲封面：\n\n"
                f"![]({cover_url})\n\n"
            )

            if adapter_instance and hasattr(adapter_instance.Send.To(detail_type, target_id), "Markdown"):
                await adapter_instance.Send.To(detail_type, target_id).Markdown(md)
            elif adapter_instance:
                await adapter_instance.Send.To(detail_type, target_id).Text(md)
        except Exception as e:
            sdk.logger.error(f"Failed to fetch/send song detail: {e}")
        
        url = await self.get_song_url(song_id)
        if not url:
            sdk.logger.error("Failed to get song URL")
            if adapter_instance:
                 await adapter_instance.Send.To(detail_type, target_id).Text("获取失败")
            return

        # Download
        temp_audio = f"temp_{song_id}.mp3"
        temp_video = f"temp_{song_id}.mp4"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(temp_audio, 'wb') as f:
                            f.write(await resp.read())
            
            # Generate Video
            await self.generate_video_from_audio(temp_audio, temp_video, duration)

            # Upload ... (rest of logic)
            
            # Upload
            user_id = event.get("user_id")
            platform = session_context.get("platform", platform)
            detail_type = session_context.get("detail_type", detail_type)
            target_id = session_context.get("target_id", target_id)
            adapter_instance = getattr(sdk.adapter, platform, sdk.adapter.yunhu)
            
            if adapter_instance:
                 # Check if adapter has Video upload method. Usually .Video or .File
                 
                 # Prepare filename
                 filename = os.path.basename(temp_video)
                 
                
                 # Manual video upload using specific API endpoint provided by user
                 # URL: https://chat-go.jwzhd.com/open-apis/v1/video/upload?token=...
                 
                 token = getattr(adapter_instance, "yhToken", None)
                 if not token:
                     sdk.logger.error("Could not find Yunhu token on adapter instance.")
                     raise Exception("Yunhu token not found")

                 upload_url = f"https://chat-go.jwzhd.com/open-apis/v1/video/upload?token={token}"
                 video_key = None
                 
                 sdk.logger.info(f"Uploading video to {upload_url}")
                 
                 async with aiohttp.ClientSession() as session:
                     with open(temp_video, 'rb') as f:
                         data = aiohttp.FormData()
                         data.add_field('video', f, filename=filename, content_type='video/mp4')
                         
                         async with session.post(upload_url, data=data) as resp:
                             resp_text = await resp.text()
                             sdk.logger.info(f"Upload response: {resp_text}")
                             try:
                                 resp_json = json.loads(resp_text)
                                 # User provided example: {"code": 1, "data": {"videoKey": "xxx"}, "msg": "success"}
                                 if resp_json.get("code") == 1 and "data" in resp_json:
                                     video_key = resp_json["data"].get("videoKey")
                             except Exception as json_err:
                                 sdk.logger.error(f"Failed to parse upload response: {json_err}")

                 if video_key:
                     sdk.logger.info(f"Video uploaded successfully. Key: {video_key}")
                     # 2. Send Message with contentType='video' and videoKey
                     await adapter_instance.call_api(
                         "/bot/send",
                         recvId=target_id,
                         recvType=detail_type,
                         contentType="video",
                         content={
                             "videoKey": video_key
                         }
                     )
                 else:
                     raise Exception(f"Failed to upload video (no videoKey returned). Response: {resp_text}")

        except Exception as e:
            sdk.logger.error(f"Process selection failed: {e}")
        finally:
            # Cleanup
            if os.path.exists(temp_audio):
                os.remove(temp_audio)
            if os.path.exists(temp_video):
                os.remove(temp_video)

