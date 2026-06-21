import discord
import asyncio
import speech_recognition as sr
import requests
import threading
import logging

# Suppress PyNaCl warnings if any
logging.getLogger("discord").setLevel(logging.WARNING)

TOKEN = "MTUxNzQxMDM5OTgyMDE4NTY4MQ.G0Plkc.0iFyQ4jh3FPAzE06kf5UI-Gy-icQ-pPAAqOoL0"

bot = discord.Bot()
connections = {}

def process_audio(sink, channel):
    print(f"[Debug] Processing audio chunk... Found {len(sink.audio_data)} speakers.")
    r = sr.Recognizer()
    for user_id, audio in sink.audio_data.items():
        user = bot.get_user(user_id)
        if not user or user.bot:
            continue
            
        audio.file.seek(0)
        
        # Debug size
        audio_size = len(audio.file.getvalue())
        print(f"[Debug] Audio from {user.name} is {audio_size} bytes.")
        
        if audio_size < 10000: # Too small, probably silence
            continue
            
        with sr.AudioFile(audio.file) as source:
            try:
                audio_data = r.record(source)
                text = r.recognize_google(audio_data, language="th-TH")
                print(f"[Discord STT] {user.name}: {text}")
                
                try:
                    requests.post("http://127.0.0.1:8000/api/discord_msg", 
                                  json={"username": user.name, "text": text},
                                  timeout=2)
                    print("[Debug] Sent to backend successfully!")
                except Exception as e:
                    print(f"Failed to send to backend: {e}")
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                print(f"STT API Error: {e}")
            except Exception as e:
                print(f"Audio processing error: {e}")

async def recording_finished_callback(sink, channel, *args):
    # 1. Immediately restart recording so we don't miss any audio
    vc = connections.get(channel.guild.id)
    if vc and vc.is_connected():
        try:
            vc.start_recording(
                discord.sinks.WaveSink(),
                recording_finished_callback,
                channel
            )
        except Exception:
            pass

    # 2. Process audio in background thread
    threading.Thread(target=process_audio, args=(sink, channel), daemon=True).start()

async def chunk_loop(guild_id):
    while guild_id in connections:
        await asyncio.sleep(5)  # Process audio every 5 seconds
        vc = connections.get(guild_id)
        if vc and vc.is_connected():
            try:
                vc.stop_recording() # This triggers the callback, which restarts it
            except Exception:
                pass
        else:
            break

@bot.slash_command(name="join", description="Make Nina join your voice channel")
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.respond("You need to be in a voice channel first!")

    channel = ctx.author.voice.channel
    
    if ctx.guild.id in connections:
        return await ctx.respond("I'm already in a voice channel here.")

    await ctx.defer() # Acknowledge the command since connecting might take a second
    
    try:
        vc = await channel.connect()
        connections[ctx.guild.id] = vc
        
        # 1. Stream microphone into Discord
        # You can change this to "Microphone (Voicemod Virtual Audio Device (WDM))"
        # You can change this to "CABLE Output (VB-Audio Virtual Cable)"
        mic_name = "Microphone (Voicemod Virtual Audio Device (WDM))"
        
        ffmpeg_opts = {
            'before_options': '-f dshow',
            'options': '-vn -ac 2 -ar 48000'
        }
        source = discord.FFmpegPCMAudio(source=f'audio="{mic_name}"', **ffmpeg_opts)
        vc.play(source)

        # 2. Start recording others
        vc.start_recording(
            discord.sinks.WaveSink(),
            recording_finished_callback,
            ctx.channel
        )
        
        # 3. Start chunk loop
        bot.loop.create_task(chunk_loop(ctx.guild.id))

        await ctx.followup.send(f"Joined {channel.name}! Listening to everyone and streaming my voice.")
    except Exception as e:
        await ctx.followup.send(f"Error joining: {e}")

@bot.slash_command(name="leave", description="Make Nina leave the voice channel")
async def leave(ctx):
    if ctx.guild.id in connections:
        vc = connections[ctx.guild.id]
        vc.stop_recording()
        del connections[ctx.guild.id]
        await vc.disconnect()
        await ctx.respond("Goodbye!")
    else:
        await ctx.respond("I'm not in a voice channel.")

@bot.event
async def on_ready():
    print(f'Discord Bot logged in as {bot.user}')
    print("Ready to join voice channels! Use /join in a server.")

if __name__ == "__main__":
    print("Starting Discord Bot...")
    bot.run(TOKEN)
