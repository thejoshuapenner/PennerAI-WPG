"use client";
import React, { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, 
  Send, 
  BookOpen, 
  Building, 
  Database, 
  Bell, 
  ChevronRight, 
  ArrowRight, 
  RefreshCw,
  Plus, 
  ExternalLink,
  Info,
  Layers,
  Activity
} from 'lucide-react';

type Message = {
  role: 'user' | 'assistant';
  content: string;
  loading?: boolean;
  citations?: Array<{ text: string; url: string }>;
  suggestions?: string[];
  correlations?: Array<{
    jurisdiction: string;
    category: string;
    summary: string;
    dollar_impact?: number;
    source: 'audit' | 'council';
    similarity?: number;
  }>;
};

type Thread = {
  id: string;
  title: string;
  messages: Message[];
  lens: 'comprehensive' | 'audits' | 'council';
};

export default function Dashboard() {
  const [lens, setLens] = useState<'comprehensive' | 'audits' | 'council'>('comprehensive');
  const [query, setQuery] = useState('');
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  
  // Lead Capture State
  const [showSubscribe, setShowSubscribe] = useState(false);
  const [subName, setSubName] = useState('');
  const [subEmail, setSubEmail] = useState('');
  const [subStatus, setSubStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [subTopic, setSubTopic] = useState('');

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const typewriterRef = useRef<HTMLSpanElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Typewriter effect in Hero state
  useEffect(() => {
    if (threads.length > 0) return;
    
    const samplePrompts = [
      "Which cities passed sales taxes for police services this year?",
      "Summarize recent audit findings for Bellevue School District.",
      "Has there been any mention of gas tax expenditures in King County?",
      "Show me procurement policy violations in county audits."
    ];
    
    let promptIndex = 0;
    let charIndex = 0;
    let isDeleting = false;
    let delay = 80;
    let timer: NodeJS.Timeout;

    const tick = () => {
      const activeText = samplePrompts[promptIndex];
      if (!typewriterRef.current) return;

      if (isDeleting) {
        charIndex--;
        typewriterRef.current.innerText = activeText.substring(0, charIndex);
        delay = 30;
      } else {
        charIndex++;
        typewriterRef.current.innerText = activeText.substring(0, charIndex);
        delay = 70;
      }

      if (!isDeleting && charIndex === activeText.length) {
        isDeleting = true;
        delay = 2500; // Pause at full query
      } else if (isDeleting && charIndex === 0) {
        isDeleting = false;
        promptIndex = (promptIndex + 1) % samplePrompts.length;
        delay = 500; // Pause before typing next
      }

      timer = setTimeout(tick, delay);
    };

    timer = setTimeout(tick, 500);
    return () => clearTimeout(timer);
  }, [threads.length]);

  // Subtle background topological wave canvas animation
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let width = window.innerWidth;
    let height = window.innerHeight;
    let mouseX = width / 2;
    let mouseY = height / 2;
    let time = 0;
    let animationFrameId: number;

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = width;
      canvas.height = height;
    };

    const handleMouseMove = (e: MouseEvent) => {
      mouseX = e.clientX;
      mouseY = e.clientY;
    };

    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', handleMouseMove);
    resize();

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      
      // Draw grid lines
      ctx.strokeStyle = 'rgba(16, 185, 129, 0.04)'; // Subtle emerald
      ctx.lineWidth = 1.0;
      
      const rows = 15;
      const cols = 25;
      const xSpacing = width / cols;
      const ySpacing = height / rows;

      ctx.beginPath();
      for (let r = 0; r <= rows; r++) {
        const yBase = r * ySpacing;
        for (let c = 0; c <= cols; c++) {
          const x = c * xSpacing;
          const dx = x - mouseX;
          const dy = yBase - mouseY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const mouseInfluence = Math.max(0, 300 - dist) / 300;
          
          const waveX = Math.sin(x * 0.003 + time) * 15;
          const waveY = Math.cos(yBase * 0.003 + time) * 15;
          const bulge = Math.pow(mouseInfluence, 3.0) * -45;

          const finalY = yBase + waveY + (bulge * (dy / (dist || 1)));
          const finalX = x + waveX + (bulge * (dx / (dist || 1)));

          if (c === 0) {
            ctx.moveTo(finalX, finalY);
          } else {
            ctx.lineTo(finalX, finalY);
          }
        }
      }
      ctx.stroke();

      time += 0.008;
      animationFrameId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', handleMouseMove);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  // Auto scroll chat to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [threads, activeThreadId]);

  // Execute conversation search
  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    const userQuery = query.trim();
    setQuery('');

    // Setup active thread or create a new one
    let currentThreadId = activeThreadId;
    let currentThread = threads.find(t => t.id === currentThreadId);

    if (!currentThread) {
      currentThreadId = Date.now().toString();
      currentThread = {
        id: currentThreadId,
        title: userQuery.length > 36 ? userQuery.substring(0, 35) + '...' : userQuery,
        messages: [],
        lens: lens
      };
      setThreads(prev => [...prev, currentThread!]);
      setActiveThreadId(currentThreadId);
    }

    // Append user message and loading state for assistant
    const userMsg: Message = { role: 'user', content: userQuery };
    const assistantMsg: Message = { 
      role: 'assistant', 
      content: '', 
      loading: true,
      citations: [],
      suggestions: [],
      correlations: []
    };

    setThreads(prev => prev.map(t => {
      if (t.id === currentThreadId) {
        return { ...t, messages: [...t.messages, userMsg, assistantMsg] };
      }
      return t;
    }));

    try {
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userQuery, lens })
      });

      if (!response.body) throw new Error("No stream body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let narrativeBuffer = "";
      let metadataJson = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const textChunk = decoder.decode(value, { stream: true });
        const lines = textChunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (!dataStr) continue;

            if (dataStr === '[DONE]') {
              // Finalize message rendering
              setThreads(prev => prev.map(t => {
                if (t.id === currentThreadId) {
                  const msgs = [...t.messages];
                  const lastIdx = msgs.length - 1;
                  if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
                    msgs[lastIdx] = { ...msgs[lastIdx], loading: false };
                  }
                  return { ...t, messages: msgs };
                }
                return t;
              }));
              break;
            }

            try {
              const data = JSON.parse(dataStr);
              
              if (data.chunk) {
                narrativeBuffer += data.chunk;
                setThreads(prev => prev.map(t => {
                  if (t.id === currentThreadId) {
                    const msgs = [...t.messages];
                    const lastIdx = msgs.length - 1;
                    if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
                      msgs[lastIdx] = { ...msgs[lastIdx], content: narrativeBuffer };
                    }
                    return { ...t, messages: msgs };
                  }
                  return t;
                }));
              } else if (data.citations || data.suggestions || data.correlations) {
                // We received metadata update
                setThreads(prev => prev.map(t => {
                  if (t.id === currentThreadId) {
                    const msgs = [...t.messages];
                    const lastIdx = msgs.length - 1;
                    if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
                      msgs[lastIdx] = {
                        ...msgs[lastIdx],
                        citations: data.citations || [],
                        suggestions: data.suggestions || [],
                        correlations: data.correlations || []
                      };
                    }
                    return { ...t, messages: msgs };
                  }
                  return t;
                }));
              }
            } catch (err) {
              // Ignore partial JSON parse errors
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
      setThreads(prev => prev.map(t => {
        if (t.id === currentThreadId) {
          const msgs = [...t.messages];
          const lastIdx = msgs.length - 1;
          if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
            msgs[lastIdx] = { 
              ...msgs[lastIdx], 
              content: "I encountered an error connecting to the civic database service. Please verify your connection parameters.", 
              loading: false 
            };
          }
          return { ...t, messages: msgs };
        }
        return t;
      }));
    }
  };

  // Submit suggestion prompt
  const handleSuggestionClick = (prompt: string) => {
    setQuery(prompt);
    setTimeout(() => {
      setQuery(prompt);
    }, 50);
  };

  // Subscribe alert trigger
  const handleSubscribe = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subEmail.trim()) return;
    setSubStatus('loading');

    try {
      const activeMsg = activeThread?.messages.find(m => m.role === 'user');
      const payload = {
        name: subName.trim() || 'Citizen User',
        email: subEmail.trim(),
        topics: subTopic.trim() || activeMsg?.content || 'General Civic Updates',
        jurisdiction: activeThread?.lens === 'comprehensive' ? 'Washington State' : activeThread?.lens === 'audits' ? 'State Auditor Office' : 'Local Municipality',
        query: activeMsg?.content || ''
      };

      const res = await fetch('/api/v1/auth/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        setSubStatus('success');
        setTimeout(() => {
          setShowSubscribe(false);
          setSubName('');
          setSubEmail('');
          setSubTopic('');
          setSubStatus('idle');
        }, 3000);
      } else {
        setSubStatus('error');
      }
    } catch (e) {
      setSubStatus('error');
    }
  };

  const activeThread = threads.find(t => t.id === activeThreadId);
  const activeAssistantMessage = activeThread?.messages.filter(m => m.role === 'assistant').slice(-1)[0];
  const activeCorrelations = activeAssistantMessage?.correlations || [];

  return (
    <div className="min-h-screen relative flex flex-col font-sans antialiased text-mist bg-obsidian">
      {/* Noise overlay and Wave canvas background */}
      <div className="grain-overlay" />
      <canvas ref={canvasRef} className="fixed inset-0 w-full h-full pointer-events-none z-0 opacity-20 transition-opacity duration-1000" />

      {/* Header */}
      <header className="z-20 border-b border-white/5 bg-obsidian/75 backdrop-blur-md px-6 py-4 flex justify-between items-center relative shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-evergreen to-emerald-600 flex items-center justify-center shadow-lg font-black text-white text-lg">P</div>
          <div>
            <h1 className="font-extrabold text-xl tracking-tight text-white flex items-center gap-1.5">
              PennerAI <span className="text-[10px] font-black tracking-widest uppercase bg-evergreen/30 text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-500/20">WPG</span>
            </h1>
            <p className="text-[10px] font-medium text-emerald-400/80 flex items-center gap-1">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500"></span>
              </span>
              Civic Intelligence Agent
            </p>
          </div>
        </div>

        {/* Lenses toggle in header (only shown when thread is active) */}
        {threads.length > 0 && (
          <div className="flex items-center bg-gunmetal p-1 rounded-xl border border-white/5 gap-1">
            <button 
              onClick={() => setLens('comprehensive')} 
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition-all ${lens === 'comprehensive' ? 'bg-evergreen text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Comprehensive</span>
            </button>
            <button 
              onClick={() => setLens('audits')} 
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition-all ${lens === 'audits' ? 'bg-evergreen text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
            >
              <BookOpen className="w-3.5 h-3.5" />
              <span>State Audits</span>
            </button>
            <button 
              onClick={() => setLens('council')} 
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide transition-all ${lens === 'council' ? 'bg-evergreen text-white shadow-md' : 'text-slate-400 hover:text-white'}`}
            >
              <Building className="w-3.5 h-3.5" />
              <span>Local Council</span>
            </button>
          </div>
        )}

        <div className="flex items-center gap-3">
          <button 
            onClick={() => {
              if (activeThread) {
                setSubTopic(activeThread.messages.find(m => m.role === 'user')?.content || '');
              }
              setShowSubscribe(true);
            }} 
            className="flex items-center gap-2 px-3 py-1.5 bg-white/5 hover:bg-white/10 rounded-xl text-xs font-bold text-slate-300 hover:text-white border border-white/5 hover:border-emerald-500/20 transition-all cursor-pointer"
          >
            <Bell className="w-3.5 h-3.5 text-emerald-400" />
            <span>Alerts</span>
          </button>
          <a 
            href="https://membrane-api.com" 
            target="_blank" 
            rel="noopener noreferrer" 
            className="text-slate-500 hover:text-emerald-400 transition-colors text-xs font-semibold tracking-wide hidden md:block"
          >
            Membrane SDK v2
          </a>
        </div>
      </header>

      {/* Main Container */}
      <div className="z-10 flex-1 flex overflow-hidden min-h-0 relative">
        
        {/* Sidebar: Message threads (only visible when threads exist) */}
        {threads.length > 0 && (
          <aside className="w-64 border-r border-white/5 bg-obsidian/40 backdrop-blur-md shrink-0 flex flex-col hidden md:flex">
            <div className="p-4 border-b border-white/5">
              <button 
                onClick={() => {
                  setActiveThreadId(null);
                }} 
                className="w-full py-2.5 px-4 bg-white/5 hover:bg-white/10 text-white rounded-xl text-xs font-bold border border-white/5 hover:border-emerald-500/20 transition-all flex items-center justify-center gap-2 cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>New Conversation</span>
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-3 custom-scrollbar space-y-2">
              <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3 pl-2">History</div>
              {threads.map(t => (
                <button
                  key={t.id}
                  onClick={() => {
                    setActiveThreadId(t.id);
                    setLens(t.lens);
                  }}
                  className={`w-full text-left p-3 rounded-xl border text-xs leading-relaxed transition-all truncate flex items-center justify-between group ${t.id === activeThreadId ? 'bg-evergreen/35 border-emerald-500/25 text-white font-bold' : 'bg-transparent border-transparent text-slate-400 hover:text-slate-200 hover:bg-white/5'}`}
                >
                  <span className="truncate pr-2">"{t.title}"</span>
                  <ChevronRight className={`w-3.5 h-3.5 text-slate-500 group-hover:text-emerald-400 transition-colors ${t.id === activeThreadId ? 'translate-x-0' : '-translate-x-1 opacity-0 group-hover:opacity-100 group-hover:translate-x-0'}`} />
                </button>
              ))}
            </div>
          </aside>
        )}

        {/* Center / Layout Workspace */}
        <div className="flex-1 flex overflow-hidden min-h-0 relative">
          
          {/* Main Chat Columns container */}
          <div className="flex-1 flex flex-col min-h-0 bg-gunmetal/20">
            
            {/* HERO STATE (Zero Threads) */}
            {threads.length === 0 ? (
              <div className="flex-1 flex flex-col justify-center items-center px-6 max-w-2xl mx-auto w-full text-center relative z-10 pb-16">
                <div className="w-20 h-20 rounded-[2rem] bg-gradient-to-br from-evergreen to-emerald-600 flex items-center justify-center shadow-[0_15px_35px_rgba(16,185,129,0.25)] border border-emerald-400/20 mb-8 transform transition-transform hover:scale-105 duration-300">
                  <Sparkles className="w-10 h-10 text-white" />
                </div>

                <h2 className="text-3xl md:text-5xl font-black tracking-tight text-white mb-4 text-balance">
                  Explore Washington <br /> Civic Intelligence
                </h2>
                <p className="text-sm md:text-base text-slate-400 mb-8 max-w-lg leading-relaxed">
                  I monitor state audits, city council minutes, and policy files in real-time. Ask any question to map facts and analyze correlations.
                </p>

                {/* Hero Lens toggles */}
                <div className="flex items-center bg-gunmetal p-1 rounded-2xl border border-white/5 mb-8 gap-1">
                  <button 
                    onClick={() => setLens('comprehensive')} 
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold tracking-wide transition-all ${lens === 'comprehensive' ? 'bg-evergreen text-white shadow-md font-extrabold' : 'text-slate-400 hover:text-white'}`}
                  >
                    <Layers className="w-4 h-4" />
                    <span>Comprehensive Index</span>
                  </button>
                  <button 
                    onClick={() => setLens('audits')} 
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold tracking-wide transition-all ${lens === 'audits' ? 'bg-evergreen text-white shadow-md font-extrabold' : 'text-slate-400 hover:text-white'}`}
                  >
                    <BookOpen className="w-4 h-4" />
                    <span>State Audits Only</span>
                  </button>
                  <button 
                    onClick={() => setLens('council')} 
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold tracking-wide transition-all ${lens === 'council' ? 'bg-evergreen text-white shadow-md font-extrabold' : 'text-slate-400 hover:text-white'}`}
                  >
                    <Building className="w-4 h-4" />
                    <span>Local Council Minutes</span>
                  </button>
                </div>

                {/* Main Hero Input Box */}
                <form onSubmit={handleSubmit} className="w-full relative group">
                  <div className="absolute inset-0 bg-evergreen/10 rounded-2xl blur-lg group-focus-within:bg-evergreen/20 transition-all" />
                  <div className="relative flex items-center bg-gunmetal border-2 border-white/5 group-focus-within:border-evergreen rounded-2xl overflow-hidden shadow-2xl transition-all pr-3">
                    <input 
                      type="text"
                      className="w-full py-4.5 px-5 bg-transparent border-none outline-none font-medium text-white placeholder-transparent text-sm"
                      placeholder=""
                      value={query}
                      onChange={e => setQuery(e.target.value)}
                    />
                    {/* Simulated placeholder typewriter */}
                    {!query && (
                      <div className="absolute left-5 pointer-events-none text-slate-500 font-medium text-sm flex items-center gap-1">
                        <span ref={typewriterRef} />
                        <span className="w-1 h-4 bg-emerald-500 animate-pulse" />
                      </div>
                    )}
                    <button 
                      type="submit" 
                      className="p-2.5 bg-evergreen hover:bg-emerald-600 rounded-xl text-white transition-all shadow-md cursor-pointer"
                    >
                      <ArrowRight className="w-4 h-4" />
                    </button>
                  </div>
                </form>

                {/* Sample Prompt Chips */}
                <div className="flex flex-wrap gap-2.5 justify-center mt-10 max-w-xl">
                  <button onClick={() => handleSuggestionClick("Bellevue School District audit findings")} className="px-3.5 py-2 bg-white/5 hover:bg-white/10 text-slate-300 rounded-xl text-xs font-semibold tracking-wide border border-white/5 hover:border-white/10 transition-all cursor-pointer">
                    Bellevue SD Audits
                  </button>
                  <button onClick={() => handleSuggestionClick("Tacoma police department budget changes")} className="px-3.5 py-2 bg-white/5 hover:bg-white/10 text-slate-300 rounded-xl text-xs font-semibold tracking-wide border border-white/5 hover:border-white/10 transition-all cursor-pointer">
                    Tacoma Police Budgets
                  </button>
                  <button onClick={() => handleSuggestionClick("Who is Transpo Group USA in contracts?")} className="px-3.5 py-2 bg-white/5 hover:bg-white/10 text-slate-300 rounded-xl text-xs font-semibold tracking-wide border border-white/5 hover:border-white/10 transition-all cursor-pointer">
                    Transpo Group Contracts
                  </button>
                </div>
              </div>
            ) : (
              // ACTIVE CHAT VIEW
              <div className="flex-1 flex flex-col min-h-0 relative z-10">
                {/* Chat Message Thread */}
                <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
                  {activeThread?.messages.map((msg, idx) => (
                    <div 
                      key={idx} 
                      className={`flex flex-col max-w-3xl ${msg.role === 'user' ? 'ml-auto items-end' : 'mr-auto items-start'}`}
                    >
                      {/* Message Bubble */}
                      <div 
                        className={`px-5 py-3.5 rounded-2xl text-sm leading-relaxed ${msg.role === 'user' ? 'bg-evergreen text-white rounded-br-none shadow-md font-medium max-w-xl' : 'bg-gunmetal border border-white/5 text-slate-200 rounded-bl-none w-full shadow-lg'}`}
                      >
                        {msg.loading ? (
                          <div className="flex items-center gap-2.5 py-2 text-slate-400">
                            <RefreshCw className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                            <span className="font-semibold tracking-wide text-xs">Penner is querying Membrane nodes...</span>
                          </div>
                        ) : (
                          <div className="space-y-4 whitespace-pre-wrap">
                            {msg.content}
                          </div>
                        )}
                      </div>

                      {/* Metadata (Citations & Suggested Actions) */}
                      {!msg.loading && msg.role === 'assistant' && (
                        <div className="mt-3.5 space-y-4 w-full">
                          
                          {/* Citations block */}
                          {msg.citations && msg.citations.length > 0 && (
                            <div className="flex flex-wrap gap-2 items-center">
                              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mr-1.5">Official Citations:</span>
                              {msg.citations.map((cite, cIdx) => (
                                <a 
                                  key={cIdx} 
                                  href={cite.url} 
                                  target="_blank" 
                                  rel="noopener noreferrer" 
                                  className="px-2.5 py-1 bg-white/5 hover:bg-white/10 border border-white/5 hover:border-emerald-500/20 text-slate-300 hover:text-white rounded-full text-xs font-bold flex items-center gap-1 transition-all"
                                >
                                  <span>{cite.text}</span>
                                  <ExternalLink className="w-2.5 h-2.5 text-slate-500" />
                                </a>
                              ))}
                            </div>
                          )}

                          {/* Quick Actions suggestion chips */}
                          {msg.suggestions && msg.suggestions.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {msg.suggestions.map((sugg, sIdx) => (
                                <button 
                                  key={sIdx} 
                                  onClick={() => handleSuggestionClick(sugg)}
                                  className="px-3 py-1.5 bg-evergreen/10 hover:bg-evergreen/35 border border-emerald-500/10 hover:border-emerald-500/30 text-emerald-400 hover:text-emerald-300 rounded-lg text-xs font-semibold transition-all cursor-pointer"
                                >
                                  {sugg}
                                </button>
                              ))}
                            </div>
                          )}

                        </div>
                      )}
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>

                {/* Bottom Input Area */}
                <div className="p-4 border-t border-white/5 bg-obsidian/45 backdrop-blur-md shrink-0">
                  <form onSubmit={handleSubmit} className="max-w-3xl mx-auto flex items-center gap-3 relative">
                    <input 
                      type="text" 
                      className="w-full py-3.5 px-5 bg-gunmetal border border-white/5 focus:border-evergreen rounded-xl outline-none font-medium text-white placeholder-slate-500 text-sm shadow-inner transition-colors"
                      placeholder="Ask a follow up question or specify a new target..."
                      value={query}
                      onChange={e => setQuery(e.target.value)}
                    />
                    <button 
                      type="submit" 
                      className="p-3 bg-evergreen hover:bg-emerald-600 text-white rounded-xl transition-all cursor-pointer shadow-md"
                    >
                      <Send className="w-4 h-4" />
                    </button>
                  </form>
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Dynamic Correlation Explorer (only shown if thread active and correlations exist) */}
          {threads.length > 0 && (
            <aside className="w-80 border-l border-white/5 bg-obsidian/30 backdrop-blur-md shrink-0 flex flex-col hidden lg:flex">
              <div className="p-4 border-b border-white/5 flex items-center justify-between shrink-0 bg-obsidian/20">
                <h3 className="text-xs font-extrabold text-white tracking-widest uppercase flex items-center gap-2">
                  <Activity className="w-4 h-4 text-emerald-400" />
                  <span>Correlation Explorer</span>
                </h3>
                <span className="text-[10px] font-black text-slate-500 bg-white/5 px-2 py-0.5 rounded-full">pgvector</span>
              </div>

              <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
                {activeCorrelations.length > 0 ? (
                  activeCorrelations.map((c, idx) => (
                    <div 
                      key={idx}
                      className="p-4 rounded-2xl bg-gunmetal/60 border border-white/5 hover:border-emerald-500/10 transition-all space-y-3 shadow-md relative overflow-hidden group"
                    >
                      <div className="absolute top-0 right-0 h-1 w-12 bg-emerald-500/50" />
                      <div className="flex justify-between items-start">
                        <div>
                          <div className="text-[10px] font-black uppercase text-emerald-400 tracking-wider">
                            {c.jurisdiction}
                          </div>
                          <div className="text-[9px] font-bold text-slate-500 mt-0.5 uppercase tracking-wide">
                            {c.category}
                          </div>
                        </div>
                        {c.similarity && (
                          <div className="text-[10px] font-extrabold text-slate-400 bg-white/5 px-1.5 py-0.5 rounded">
                            {Math.round(c.similarity * 100)}% Match
                          </div>
                        )}
                      </div>

                      <p className="text-xs text-slate-300 leading-relaxed">
                        {c.summary}
                      </p>

                      {c.dollar_impact ? (
                        <div className="text-xs font-bold text-rose-400/90 flex items-center gap-1 bg-rose-500/5 py-1 px-2.5 rounded-lg border border-rose-500/5 w-fit">
                          <span>Financial impact: ${c.dollar_impact.toLocaleString()}</span>
                        </div>
                      ) : null}

                      <div className="flex items-center gap-2 pt-1">
                        <span className={`text-[8px] font-black tracking-widest uppercase px-2 py-0.5 rounded ${c.source === 'audit' ? 'bg-purple-500/10 text-purple-400 border border-purple-500/10' : 'bg-blue-500/10 text-blue-400 border border-blue-500/10'}`}>
                          {c.source === 'audit' ? 'SAO Audit' : 'City Council'}
                        </span>
                        <button 
                          onClick={() => handleSuggestionClick(`Tell me more about the ${c.jurisdiction} ${c.category} findings.`)}
                          className="text-[9px] font-black text-slate-400 hover:text-emerald-400 transition-colors uppercase ml-auto tracking-wider flex items-center gap-0.5"
                        >
                          <span>Investigate</span>
                          <ArrowRight className="w-2.5 h-2.5" />
                        </button>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="flex flex-col items-center justify-center text-center py-20 px-4 text-slate-500 space-y-3">
                    <Database className="w-8 h-8 text-slate-600" />
                    <div>
                      <h4 className="text-xs font-bold text-slate-400">Database Context Standby</h4>
                      <p className="text-[10px] text-slate-500 mt-1 max-w-[180px] mx-auto leading-relaxed">
                        Submit a question to filter nodes. Semantic correlations will populate here automatically.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </aside>
          )}

        </div>
      </div>

      {/* Footer Powered By */}
      <footer className="z-20 border-t border-white/5 bg-obsidian py-3 px-6 text-center text-[10px] font-medium text-slate-600 flex justify-between items-center relative shrink-0">
        <span>&copy; 2026 Penner Strategy LLC. All rights reserved.</span>
        <span className="flex items-center gap-1 text-slate-500">
          <Info className="w-3 h-3 text-emerald-400" />
          <span>Semantic Caching & zero-retention logging active on membrane-api.com</span>
        </span>
      </footer>

      {/* Alerts / Monitoring Modal */}
      {showSubscribe && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-obsidian/70 backdrop-blur-sm">
          <div className="bg-gunmetal border border-white/5 rounded-3xl p-6 md:p-8 max-w-md w-full shadow-2xl relative">
            <button 
              onClick={() => {
                setShowSubscribe(false);
                setSubStatus('idle');
              }} 
              className="absolute top-4 right-4 text-slate-500 hover:text-white transition-colors cursor-pointer text-sm"
            >
              ✕
            </button>

            <div className="flex items-center gap-4 mb-6">
              <div className="w-12 h-12 rounded-2xl bg-evergreen/30 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                <Bell className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-extrabold text-white">Create Civic Alert</h3>
                <p className="text-xs text-slate-400">Penner will monitor this issue and email you when new findings surface.</p>
              </div>
            </div>

            {subStatus === 'success' ? (
              <div className="bg-evergreen/10 border border-emerald-500/20 p-5 rounded-2xl text-center space-y-3 py-8">
                <div className="text-emerald-400 text-3xl">✓</div>
                <h4 className="text-sm font-bold text-white uppercase tracking-wider">Alert Active</h4>
                <p className="text-xs text-slate-300">You're subscribed! I'll email you alerts on this topic immediately.</p>
              </div>
            ) : (
              <form onSubmit={handleSubscribe} className="space-y-4">
                <div>
                  <label className="block text-[10px] font-extrabold text-slate-400 uppercase tracking-wider mb-2">
                    Your Name
                  </label>
                  <input 
                    type="text" 
                    required
                    placeholder="Jane Citizen"
                    className="w-full px-4 py-3 bg-obsidian border border-white/5 focus:border-evergreen rounded-xl outline-none text-sm text-white transition-colors"
                    value={subName}
                    onChange={e => setSubName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-extrabold text-slate-400 uppercase tracking-wider mb-2">
                    Your Email
                  </label>
                  <input 
                    type="email" 
                    required
                    placeholder="jane@example.com"
                    className="w-full px-4 py-3 bg-obsidian border border-white/5 focus:border-evergreen rounded-xl outline-none text-sm text-white transition-colors"
                    value={subEmail}
                    onChange={e => setSubEmail(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-extrabold text-slate-400 uppercase tracking-wider mb-2">
                    Topic / Query of Interest
                  </label>
                  <textarea 
                    rows={2}
                    placeholder="e.g. Bellevue school district audit findings, interfund loan approvals"
                    className="w-full px-4 py-3 bg-obsidian border border-white/5 focus:border-evergreen rounded-xl outline-none text-sm text-white transition-colors resize-none"
                    value={subTopic}
                    onChange={e => setSubTopic(e.target.value)}
                  />
                </div>

                {subStatus === 'error' && (
                  <p className="text-xs font-bold text-red-400">Failed to register subscription. Please try again.</p>
                )}

                <button 
                  type="submit" 
                  disabled={subStatus === 'loading'}
                  className="w-full py-3.5 bg-evergreen hover:bg-emerald-600 disabled:bg-evergreen/40 text-white rounded-xl text-sm font-bold shadow-lg transition-all cursor-pointer flex items-center justify-center gap-2"
                >
                  {subStatus === 'loading' ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Saving alerts...</span>
                    </>
                  ) : (
                    <span>Register Active Monitor</span>
                  )}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
