import React, { useState, useEffect, useRef } from 'react';
import { Mic, MicOff, Play, Square, Terminal, Video } from 'lucide-react';

interface ChatMessage {
  sender: string;
  text: string;
}

function App() {
  const [status, setStatus] = useState('Waiting to Start...');
  const [ninaRunning, setNinaRunning] = useState(false);
  const [ollamaOnline, setOllamaOnline] = useState(false);
  const [micOn, setMicOn] = useState(false);
  const [chatLog, setChatLog] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [volume, setVolume] = useState(0);
  const [currentStream, setCurrentStream] = useState('');
  const currentStreamRef = useRef('');
  const [micList, setMicList] = useState<string[]>([]);
  const [selectedMic, setSelectedMic] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'chat' | 'log' | 'memory'>('chat');
  const [memoryText, setMemoryText] = useState('');

  const ws = useRef<WebSocket | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch('http://localhost:8000/api/get_memories')
      .then(res => res.json())
      .then(data => {
        if (data.memories) {
          setMemoryText(data.memories.join('\n'));
        }
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    // Connect to Python Backend
    ws.current = new WebSocket('ws://localhost:8000/ws');
    
    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      switch(data.type) {
        case 'state':
          setNinaRunning(data.content.is_running);
          setMicOn(data.content.is_mic_on);
          if (data.content.mic_list) setMicList(data.content.mic_list);
          setSelectedMic(data.content.selected_mic_index);
          break;
        case 'mic_changed':
          setSelectedMic(data.content);
          break;
        case 'status':
          setStatus(data.content);
          break;
        case 'nina_status':
          setNinaRunning(data.content === '🟢');
          break;
        case 'ollama_status':
          setOllamaOnline(data.content === '🟢');
          break;
        case 'mic_status':
          setMicOn(data.content === 'ON');
          break;
        case 'volume':
          setVolume(data.content);
          break;
        case 'chat':
          setChatLog(prev => [...prev, data.content]);
          break;
        case 'stream_start':
          setCurrentStream('');
          currentStreamRef.current = '';
          break;
        case 'stream_chunk':
          setCurrentStream(prev => prev + data.content);
          currentStreamRef.current += data.content;
          break;
        case 'stream_end':
          const finalStreamText = currentStreamRef.current;
          const cleanStream = finalStreamText.replace(/[\u200B-\u200D\uFEFF]/g, '').trim();
          if (cleanStream !== '' && cleanStream.toLowerCase() !== 'null') {
            setChatLog(prev => [...prev, { sender: 'Nina', text: finalStreamText }]);
          }
          setCurrentStream('');
          currentStreamRef.current = '';
          break;
        case 'memories_updated':
          setMemoryText(data.content.join('\n'));
          break;
      }
    };

    return () => ws.current?.close();
  }, []); // Empty dependency array to connect only once

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatLog, currentStream]);

  const apiCall = async (endpoint: string, body?: any) => {
    try {
      await fetch(`http://localhost:8000${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
      });
    } catch (e) {
      console.error(e);
    }
  };

  const saveMemories = () => {
    const memArray = memoryText.split('\n').filter(m => m.trim() !== '');
    apiCall('/api/save_memories', { memories: memArray });
  };

  return (
    <div className="flex h-screen bg-background text-text font-sans">
      
      {/* Sidebar */}
      <div className="w-64 bg-surface flex flex-col justify-between border-r border-surfaceHighlight">
        <div>
          <div className="p-6 text-2xl font-bold text-primary tracking-wide text-center">
            Nina Controller
          </div>
          
          <div className="px-4 space-y-3">
            <button onClick={() => apiCall('/api/toggle_ollama')} className="w-full flex items-center justify-center space-x-2 py-3 bg-primary hover:bg-primaryHover rounded-lg transition text-white font-medium">
              <Terminal size={18} /> <span>Toggle Ollama</span>
            </button>
            <button onClick={() => apiCall('/api/start_vts')} className="w-full flex items-center justify-center space-x-2 py-3 bg-primary hover:bg-primaryHover rounded-lg transition text-white font-medium">
              <Video size={18} /> <span>VTube Studio</span>
            </button>
            <button onClick={() => apiCall('/api/toggle_nina')} className={`w-full flex items-center justify-center space-x-2 py-3 rounded-lg transition text-white font-medium ${ninaRunning ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'}`}>
              {ninaRunning ? <><Square size={18} fill="currentColor" /> <span>Stop Nina-sama</span></> : <><Play size={18} fill="currentColor" /> <span>Start Nina-sama</span></>}
            </button>
          </div>
        </div>
        
        <div className="p-4 border-t border-surfaceHighlight text-center text-sm">
          <p className="text-textMuted mb-2">Status:</p>
          <p className="text-primary font-semibold min-h-[40px] flex items-center justify-center">{status}</p>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col bg-background">
        
        {/* Top Bar */}
        <div className="h-16 border-b border-surfaceHighlight flex items-center justify-between px-6 bg-surface">
          <div className="flex space-x-4">
            <div className={`flex items-center space-x-2 ${ollamaOnline ? 'text-green-500' : 'text-red-500'}`}>
              <span>🦙</span> <div className={`w-3 h-3 rounded-full ${ollamaOnline ? 'bg-green-500' : 'bg-red-500'}`}></div>
            </div>
            <div className={`flex items-center space-x-2 ${ninaRunning ? 'text-green-500' : 'text-red-500'}`}>
              <span>❤️</span> <div className={`w-3 h-3 rounded-full ${ninaRunning ? 'bg-green-500' : 'bg-red-500'}`}></div>
            </div>
          </div>
          
          <div className="flex items-center space-x-4">
            <select
              className="bg-surfaceHighlight text-xs text-text border border-gray-700 rounded p-2 max-w-[150px] outline-none"
              value={selectedMic === null ? "" : selectedMic}
              title={selectedMic !== null && micList[selectedMic] ? micList[selectedMic] : "Default OS Mic"}
              onChange={(e) => apiCall('/api/set_mic', { index: e.target.value === "" ? null : parseInt(e.target.value) })}
            >
              <option value="">Default OS Mic</option>
              {micList.map((mic, i) => (
                <option key={i} value={i}>{mic.substring(0, 30)}{mic.length > 30 ? '...' : ''}</option>
              ))}
            </select>
            {/* Volume Bar */}
            <div className="w-24 h-2 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-primary transition-all duration-75" style={{ width: `${volume * 100}%` }}></div>
            </div>
            <button onClick={() => apiCall('/api/toggle_mic')} className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-bold transition ${micOn ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'}`}>
              {micOn ? <Mic size={16} /> : <MicOff size={16} />}
              <span>Mic: {micOn ? 'ON' : 'OFF'}</span>
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-surfaceHighlight bg-surface text-sm">
          <button 
            className={`px-6 py-3 font-semibold transition ${activeTab === 'chat' ? 'text-primary border-b-2 border-primary' : 'text-textMuted hover:text-text'}`}
            onClick={() => setActiveTab('chat')}
          >
            Chat
          </button>
          <button 
            className={`px-6 py-3 font-semibold transition ${activeTab === 'log' ? 'text-primary border-b-2 border-primary' : 'text-textMuted hover:text-text'}`}
            onClick={() => setActiveTab('log')}
          >
            Log
          </button>
          <button 
            className={`px-6 py-3 font-semibold transition ${activeTab === 'memory' ? 'text-primary border-b-2 border-primary' : 'text-textMuted hover:text-text'}`}
            onClick={() => setActiveTab('memory')}
          >
            Long-term Memory
          </button>
        </div>

        {/* Main Area */}
        {activeTab === 'memory' ? (
          <div className="flex-1 flex flex-col p-6 overflow-hidden">
            <div className="mb-4 text-sm text-textMuted">
              Edit Nina's long-term memories below. Each line represents one memory.
            </div>
            <textarea 
              className="flex-1 bg-surface border border-surfaceHighlight rounded-lg p-4 text-text focus:outline-none focus:border-primary resize-none font-mono text-sm mb-4"
              value={memoryText}
              onChange={(e) => setMemoryText(e.target.value)}
            />
            <div className="flex justify-end">
              <button onClick={saveMemories} className="bg-primary hover:bg-primaryHover text-white px-6 py-2 rounded-lg font-bold transition">
                Save Memories
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Chat/Log View */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {chatLog.filter(msg => {
                const cleanText = msg.text.replace(/[\u200B-\u200D\uFEFF]/g, '').trim();
                if (cleanText === '' || cleanText.toLowerCase() === 'null') return false;
                if (activeTab === 'chat' && msg.sender === 'System') return false;
                return true;
              }).map((msg, i) => {
                const isUser = msg.sender.startsWith('You');
                const isSystem = msg.sender === 'System';
                return (
                <div key={i} className={`flex flex-col ${isUser ? 'items-end' : isSystem ? 'items-center' : 'items-start'}`}>
                  {isSystem ? (
                    <div className="text-xs text-yellow-500 font-bold mb-1 px-4 py-1 bg-yellow-500/10 rounded-full border border-yellow-500/20">
                      {msg.text}
                    </div>
                  ) : (
                    <>
                      <div className="text-xs text-textMuted mb-1">{msg.sender}</div>
                      <div className={`px-4 py-2 rounded-xl max-w-[80%] ${isUser ? 'bg-primary text-white rounded-br-none' : 'bg-surfaceHighlight text-text rounded-bl-none'}`}>
                        {msg.text}
                      </div>
                    </>
                  )}
                </div>
              )})}
              {currentStream && (
                <div className="flex flex-col items-start">
                  <div className="text-xs text-textMuted mb-1">Nina</div>
                  <div className="px-4 py-2 rounded-xl max-w-[80%] bg-surfaceHighlight text-text rounded-bl-none">
                    {currentStream}<span className="animate-pulse">_</span>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-4 bg-surface border-t border-surfaceHighlight">
              <form onSubmit={(e) => { e.preventDefault(); apiCall('/api/send_text', { text: inputText }); setInputText(''); }} className="flex space-x-2">
                <input 
                  type="text" 
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Type a message to Nina-sama..." 
                  className="flex-1 bg-background border border-surfaceHighlight rounded-lg px-4 py-3 text-text focus:outline-none focus:border-primary transition"
                />
                <button type="submit" className="bg-primary hover:bg-primaryHover text-white px-6 py-3 rounded-lg font-bold transition">
                  Send 🎀
                </button>
              </form>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default App;
