const { Client, GatewayIntentBits } = require('discord.js');
const { joinVoiceChannel, createAudioPlayer, createAudioResource, StreamType, EndBehaviorType } = require('@discordjs/voice');
const { spawn } = require('child_process');
const ffmpegPath = require('ffmpeg-static');

// Require snazzah/davey so @discordjs/voice automatically patches for DAVE protocol
require('@snazzah/davey');

const TOKEN = "MTUxNzQxMDM5OTgyMDE4NTY4MQ.G0Plkc.0iFyQ4jh3FPAzE06kf5UI-Gy-icQ-pPAAqOoL0";

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
    ],
});

let connections = new Map();

// Helper to write WAV header
function writeWavHeader(buffer, numChannels, sampleRate, bitsPerSample) {
    const header = Buffer.alloc(44);
    header.write('RIFF', 0);
    header.writeUInt32LE(36 + buffer.length, 4);
    header.write('WAVE', 8);
    header.write('fmt ', 12);
    header.writeUInt32LE(16, 16); 
    header.writeUInt16LE(1, 20); 
    header.writeUInt16LE(numChannels, 22);
    header.writeUInt32LE(sampleRate, 24);
    header.writeUInt32LE(sampleRate * numChannels * (bitsPerSample / 8), 28);
    header.writeUInt16LE(numChannels * (bitsPerSample / 8), 32); 
    header.writeUInt16LE(bitsPerSample, 34);
    header.write('data', 36);
    header.writeUInt32LE(buffer.length, 40);
    return Buffer.concat([header, buffer]);
}

client.on('ready', () => {
    console.log(`[Discord] Logged in as ${client.user.tag}!`);
    console.log(`[Discord] Ready to join voice channels. DAVE Protocol enabled.`);
});

client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;

    if (interaction.commandName === 'join') {
        const member = interaction.member;
        if (!member || !member.voice.channel) {
            return interaction.reply({ content: 'You need to be in a voice channel first!', ephemeral: true });
        }

        await interaction.deferReply();
        const channel = member.voice.channel;

        try {
            const connection = joinVoiceChannel({
                channelId: channel.id,
                guildId: channel.guild.id,
                adapterCreator: channel.guild.voiceAdapterCreator,
                selfDeaf: false,
            });

            connections.set(channel.guild.id, connection);

            // 1. Setup Audio Sending (Nina speaking)
            const micName = 'Microphone (Voicemod Virtual Audio Device (WDM))';
            const ffmpeg = spawn(ffmpegPath, [
                '-f', 'dshow',
                '-i', `audio=${micName}`,
                '-f', 's16le',
                '-ar', '48000',
                '-ac', '2',
                'pipe:1'
            ]);

            ffmpeg.stderr.on('data', (data) => {
                // Uncomment to debug ffmpeg
                // console.log(`ffmpeg err: ${data}`);
            });

            const player = createAudioPlayer();
            const resource = createAudioResource(ffmpeg.stdout, { inputType: StreamType.Raw });
            player.play(resource);
            connection.subscribe(player);

            // 2. Setup Audio Receiving (Listening to users)
            const prism = require('prism-media');
            
            connection.receiver.speaking.on('start', (userId) => {
                const user = client.users.cache.get(userId);
                if (!user || user.bot) return;

                const stream = connection.receiver.subscribe(userId, {
                    end: {
                        behavior: EndBehaviorType.AfterSilence,
                        duration: 1500, // Wait 1.5s of silence before ending chunk
                    },
                });

                // Decode Opus packets to Raw PCM
                const decoder = new prism.opus.Decoder({ rate: 48000, channels: 2, frameSize: 960 });
                const pcmStream = stream.pipe(decoder);

                const chunks = [];
                pcmStream.on('data', (chunk) => {
                    chunks.push(chunk);
                });

                pcmStream.on('end', async () => {
                    const pcmBuffer = Buffer.concat(chunks);
                    if (pcmBuffer.length < 50000) return; // Ignore very short noises (50k bytes ~ 0.25 seconds of PCM)

                    console.log(`[Audio] Received ${pcmBuffer.length} bytes of PCM audio from ${user.username}`);
                    
                    const wavBuffer = writeWavHeader(pcmBuffer, 2, 48000, 16);
                    
                    // Native fetch in Node 22+ handles FormData seamlessly
                    const blob = new Blob([wavBuffer], { type: 'audio/wav' });
                    const formData = new FormData();
                    formData.append('username', user.username);
                    formData.append('file', blob, 'audio.wav');

                    try {
                        const response = await fetch('http://127.0.0.1:8000/api/discord_audio', {
                            method: 'POST',
                            body: formData,
                        });
                        if (response.ok) {
                            console.log(`[STT] Sent audio to backend for ${user.username}`);
                        }
                    } catch (error) {
                        console.error(`[Error] Failed to send audio to backend:`, error.message);
                    }
                });
            });

            await interaction.editReply(`Joined ${channel.name}! Listening to everyone and streaming my voice.`);
        } catch (error) {
            console.error(error);
            try { await interaction.editReply(`Error joining: ${error.message}`); } catch (e) {}
        }
    } else if (interaction.commandName === 'leave') {
        await interaction.deferReply();
        const connection = connections.get(interaction.guildId);
        if (connection) {
            connection.destroy();
            connections.delete(interaction.guildId);
            await interaction.editReply('Left the voice channel.');
        } else {
            await interaction.editReply('I am not in a voice channel.');
        }
    }
});

client.login(TOKEN);
