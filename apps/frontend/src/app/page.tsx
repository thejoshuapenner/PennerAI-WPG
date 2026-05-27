"use client";
import React, { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { WaveCanvas } from '../components/ui/WaveCanvas';
import { SearchForm } from '../components/ui/SearchForm';
import { MessageBubble } from '../components/chat/MessageBubble';
import { CorrelationCard } from '../components/explorer/CorrelationCard';
import { DocumentViewer } from '../components/explorer/DocumentViewer';
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
  Activity,
  ArrowLeft,
  ShieldAlert,
  Coins,
  X
} from 'lucide-react';

type Message = {
  role: 'user' | 'assistant';
  content: string;
  loading?: boolean;
  status?: 'intent' | 'searching' | 'correlating' | 'synthesizing';
  statusMessage?: string;
  citations?: Array<{ text: string; url: string }>;
  dbCitations?: Array<{ text: string; url: string; type: 'audit' | 'council' | 'bill' | 'grant' }>;
  suggestions?: string[];
  correlations?: Array<{
    jurisdiction: string;
    category: string;
    summary: string;
    dollar_impact?: number;
    source: 'audit' | 'council' | 'bill' | 'grant';
    similarity?: number;
  }>;
  lensMetadata?: {
    counts: {
      audits: number;
      council: number;
      bills: number;
      grants: number;
    };
    bill_details?: any;
    grant_details?: any;
  };
};

type Thread = {
  id: string;
  title: string;
  messages: Message[];
  lens: 'comprehensive' | 'audits' | 'council' | 'bills' | 'grants';
};

const getApiUrl = () => {
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return 'http://localhost:8002';
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || 'https://penner-policy-api.loca.lt';
};

// Globally override fetch to automatically inject Bypass-Tunnel-Reminder header for localtunnel
if (typeof window !== 'undefined') {
  const win = window as any;
  if (!win.__fetch_override_applied__) {
    win.__fetch_override_applied__ = true;
    const originalFetch = window.fetch;
    window.fetch = function (input: any, init: any) {
      let url = "";
      if (typeof input === 'string') {
        url = input;
      } else if (input && typeof input === 'object' && 'url' in input) {
        url = input.url;
      }
      
      if (url && (url.includes('loca.lt') || url.includes('localhost:8002'))) {
        init = init || {};
        init.headers = init.headers || {};
        if (init.headers instanceof Headers) {
          init.headers.set('Bypass-Tunnel-Reminder', 'true');
        } else if (Array.isArray(init.headers)) {
          init.headers.push(['Bypass-Tunnel-Reminder', 'true']);
        } else {
          init.headers['Bypass-Tunnel-Reminder'] = 'true';
        }
      }
      return originalFetch.call(this, input, init);
    };
  }
}


// Simple helper to parse and render bold markdown and citation links
const parseInlineMarkdown = (
  text: string, 
  citations: Array<{ text: string; url: string }> = [],
  dbCitations: Array<{ text: string; url: string; type: 'audit' | 'council' | 'bill' | 'grant' }> = [],
  onCitationClick: (cite: { text: string; url: string }, type: 'audit' | 'council' | 'web' | 'bill' | 'grant') => void,
  activeLens: 'comprehensive' | 'audits' | 'council' | 'bills' | 'grants'
): React.ReactNode => {
  const parts = text.split('**');
  return parts.map((part, i) => {
    const isBold = i % 2 === 1;
    
    // Parse markdown links like [Link Text](url), brackets like [1], [2], [DB-1], [DB-2], or 7-digit report numbers (e.g., 1037463)
    const citationRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\[(\d+)\]|\[DB-(\d+)\]|\b(1\d{6})\b/gi;
    const subParts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match;
    
    while ((match = citationRegex.exec(part)) !== null) {
      const matchIndex = match.index;
      
      if (matchIndex > lastIndex) {
        subParts.push(part.substring(lastIndex, matchIndex));
      }
      
      if (match[1] && match[2]) {
        // Standard markdown link [Link Text](url)
        subParts.push(
          <a 
            key={`link-${matchIndex}`}
            href={match[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-evergreen hover:text-emerald-800 underline font-bold transition-all cursor-pointer inline-flex items-center gap-0.5"
          >
            {match[1]}
            <ExternalLink className="w-2.5 h-2.5 inline-block opacity-80" />
          </a>
        );
      } else if (match[3]) {
        // Standard bracket [N] citation (Web/General citation)
        const num = parseInt(match[3], 10);
        if (citations && num > 0 && num <= citations.length) {
          const cite = citations[num - 1];
          const isDimmed = activeLens !== 'comprehensive';
          subParts.push(
            <button 
              key={`cite-web-${num}-${matchIndex}`}
              onClick={(e) => {
                e.preventDefault();
                onCitationClick(cite, 'web');
              }}
              className={`inline-flex items-center justify-center w-4 h-4 mx-0.5 text-[8px] font-black bg-slate-200 hover:bg-slate-300 text-slate-700 rounded-full border border-slate-300/40 hover:border-slate-400 transition-all shadow-sm cursor-pointer align-super ${isDimmed ? 'opacity-25' : ''}`}
              title={cite.text}
            >
              {num}
            </button>
          );
        } else {
          subParts.push(match[0]);
        }
      } else if (match[4]) {
        // Database citation [DB-N]
        const num = parseInt(match[4], 10);
        if (dbCitations && num > 0 && num <= dbCitations.length) {
          const cite = dbCitations[num - 1];
          
          // Lens dimming rules
          let isDimmed = false;
          if (activeLens !== 'comprehensive') {
            if (activeLens === 'audits' && cite.type !== 'audit') isDimmed = true;
            else if (activeLens === 'council' && cite.type !== 'council') isDimmed = true;
            else if (activeLens === 'bills' && cite.type !== 'bill') isDimmed = true;
            else if (activeLens === 'grants' && cite.type !== 'grant') isDimmed = true;
          }
          
          let colorClass = "bg-emerald-50 border-emerald-300/30 text-emerald-800 hover:bg-emerald-100";
          if (cite.type === 'audit') {
            colorClass = "bg-purple-50 border-purple-300/30 text-purple-800 hover:bg-purple-100";
          } else if (cite.type === 'council') {
            colorClass = "bg-blue-50 border-blue-300/30 text-blue-800 hover:bg-blue-100";
          } else if (cite.type === 'bill') {
            colorClass = "bg-rose-50 border-rose-300/30 text-rose-800 hover:bg-rose-100";
          }
          
          subParts.push(
            <button 
              key={`cite-db-${num}-${matchIndex}`}
              onClick={(e) => {
                e.preventDefault();
                onCitationClick(cite, cite.type);
              }}
              className={`inline-flex items-center justify-center px-1.5 h-4.5 mx-0.5 text-[8px] font-black rounded border transition-all shadow-sm cursor-pointer align-super ${colorClass} ${isDimmed ? 'opacity-25' : ''}`}
              title={cite.text}
            >
              DB-{num}
            </button>
          );
        } else {
          subParts.push(match[0]);
        }
      } else if (match[5]) {
        // SAO Report number (e.g. 1037463)
        const reportNum = match[5];
        subParts.push(
          <button 
            key={`cite-sao-${reportNum}-${matchIndex}`}
            onClick={(e) => {
              e.preventDefault();
              onCitationClick({
                text: `SAO Audit Report ${reportNum}`,
                url: `https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn=${reportNum}&isFinding=false&sp=false`
              }, 'audit');
            }}
            className="inline-flex items-center text-purple-600 hover:text-purple-800 underline font-bold transition-all cursor-pointer bg-transparent border-none p-0 mx-0.5 text-xs md:text-sm align-baseline"
            title={`View SAO Audit Report ${reportNum}`}
          >
            {reportNum}
          </button>
        );
      }
      
      lastIndex = citationRegex.lastIndex;
    }
    
    if (lastIndex < part.length) {
      subParts.push(part.substring(lastIndex));
    }
    
    if (isBold) {
      return <strong key={i} className="font-extrabold text-slate-900">{subParts}</strong>;
    }
    return <span key={i}>{subParts}</span>;
  });
};

const renderMessageContent = (
  content: string, 
  citations: Array<{ text: string; url: string }> = [],
  dbCitations: Array<{ text: string; url: string; type: 'audit' | 'council' | 'bill' | 'grant' }> = [],
  onCitationClick: (cite: { text: string; url: string }, type: 'audit' | 'council' | 'web' | 'bill' | 'grant') => void,
  activeLens: 'comprehensive' | 'audits' | 'council' | 'bills' | 'grants'
) => {
  if (!content) return null;
  const cleanedContent = content.replace(/\[([^\]]+)\]\s*\((https?:\/\/[^\s)]+)\)/g, '[$1]($2)');
  const lines = cleanedContent.split('\n');
  const elements: React.ReactNode[] = [];
  let currentTable: string[][] = [];
  let isTable = false;
  let currentList: string[] = [];
  let isList = false;

  const flushTable = (key: string) => {
    if (currentTable.length === 0) return null;
    
    let startIdx = 0;
    let headers: string[] = [];
    
    if (currentTable.length > 1 && currentTable[1].every(cell => cell.trim().startsWith(':') || cell.trim().startsWith('-') || cell.trim().endsWith(':'))) {
      headers = currentTable[0];
      startIdx = 2;
    } else if (currentTable.length > 0) {
      headers = currentTable[0];
      startIdx = 1;
    }
    
    const rows = currentTable.slice(startIdx);
    
    const rendered = (
      <div key={key} className="overflow-x-auto my-3 border border-slate-200 rounded-xl shadow-sm bg-white">
        <table className="min-w-full divide-y divide-slate-200 text-xs">
          {headers.length > 0 && (
            <thead className="bg-slate-50 font-bold text-slate-700">
              <tr>
                {headers.map((h, i) => (
                  <th key={i} className="px-4 py-3 text-left font-black border-b border-slate-200">
                    {parseInlineMarkdown(h, citations, dbCitations, onCitationClick, activeLens)}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody className="divide-y divide-slate-100 bg-white">
            {rows.map((row, rIdx) => (
              <tr key={rIdx} className="hover:bg-slate-50/50 transition-colors">
                {row.map((cell, cIdx) => (
                  <td key={cIdx} className="px-4 py-2.5 text-slate-700 font-medium">
                    {parseInlineMarkdown(cell, citations, dbCitations, onCitationClick, activeLens)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    
    currentTable = [];
    isTable = false;
    return rendered;
  };

  const flushList = (key: string) => {
    if (currentList.length === 0) return null;
    const rendered = (
      <ul key={key} className="list-disc pl-5 my-2 space-y-1.5 text-xs md:text-sm text-slate-705 font-medium">
        {currentList.map((item, idx) => (
          <li key={idx}>
            {parseInlineMarkdown(item, citations, dbCitations, onCitationClick, activeLens)}
          </li>
        ))}
      </ul>
    );
    currentList = [];
    isList = false;
    return rendered;
  };

  let elementKey = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      if (isList) {
        elements.push(flushList(`list-${elementKey++}`));
      }
      isTable = true;
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      currentTable.push(cells);
      continue;
    }

    if (trimmed.startsWith('* ') || trimmed.startsWith('- ')) {
      if (isTable) {
        elements.push(flushTable(`table-${elementKey++}`));
      }
      isList = true;
      currentList.push(trimmed.slice(2));
      continue;
    }

    if (isTable) {
      elements.push(flushTable(`table-${elementKey++}`));
    }
    if (isList) {
      elements.push(flushList(`list-${elementKey++}`));
    }

    if (trimmed === '') {
      elements.push(<div key={`space-${elementKey++}`} className="h-2" />);
    } else {
      if (trimmed.startsWith('### ')) {
        elements.push(
          <h3 key={`h3-${elementKey++}`} className="text-sm font-bold text-slate-900 mt-4 mb-2">
            {parseInlineMarkdown(trimmed.slice(4), citations, dbCitations, onCitationClick, activeLens)}
          </h3>
        );
      } else if (trimmed.startsWith('#### ')) {
        elements.push(
          <h4 key={`h4-${elementKey++}`} className="text-xs font-extrabold text-slate-800 mt-3 mb-1 uppercase tracking-wider">
            {parseInlineMarkdown(trimmed.slice(5), citations, dbCitations, onCitationClick, activeLens)}
          </h4>
        );
      } else {
        elements.push(
          <p key={`p-${elementKey++}`} className="text-xs md:text-sm leading-relaxed text-slate-700 font-medium">
            {parseInlineMarkdown(line, citations, dbCitations, onCitationClick, activeLens)}
          </p>
        );
      }
    }
  }

  if (isTable) elements.push(flushTable(`table-${elementKey++}`));
  if (isList) elements.push(flushList(`list-${elementKey++}`));

  return <div className="space-y-2">{elements}</div>;
};

export default function Dashboard() {
  const [lens, setLens] = useState<'comprehensive' | 'audits' | 'council' | 'bills' | 'grants'>('comprehensive');
  const [query, setQuery] = useState('');
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  
  // Stream ref and interval refs for render throttling
  const streamTextRef = useRef('');
  const flushIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Resizable Explorer & Collapsible States (stored in CSS variable, initial value set on mount)
  useEffect(() => {
    document.documentElement.style.setProperty('--explorer-width', '320px');
  }, []);

  const [explorerTab, setExplorerTab] = useState<'correlations' | 'viewer'>('correlations');
  const [selectedDocument, setSelectedDocument] = useState<{ text: string; url: string; type: 'audit' | 'council' | 'web' | 'bill' | 'grant' } | null>(null);
  const isResizing = useRef(false);
  const [resizing, setResizing] = useState(false);
  const mouseUpRef = useRef<(() => void) | null>(null);

  // Surfaced Correlations / Insights
  const [homeCorrelations, setHomeCorrelations] = useState<any[]>([]);
  const [selectedHomeCorr, setSelectedHomeCorr] = useState<any | null>(null);
  const [showCorrModal, setShowCorrModal] = useState(false);
  
  // Lead Capture State
  const [showSubscribe, setShowSubscribe] = useState(false);
  const [subName, setSubName] = useState('');
  const [subEmail, setSubEmail] = useState('');
  const [subStatus, setSubStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [subTopic, setSubTopic] = useState('');

  // Bug Report / Civic Tip State
  const [showBugReport, setShowBugReport] = useState(false);
  const [bugName, setBugName] = useState('');
  const [bugEmail, setBugEmail] = useState('');
  const [bugType, setBugType] = useState<'bug' | 'tip'>('bug');
  const [bugDescription, setBugDescription] = useState('');
  const [bugStatus, setBugStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [showBetaDisclosure, setShowBetaDisclosure] = useState(false);
  const [homeSuggestions, setHomeSuggestions] = useState<string[]>([
    "What are the recent audit findings for Bellevue School District?",
    "How has the Tacoma police department's budget changed recently?",
    "Which local government contracts involve Transpo Group USA?"
  ]);

  useEffect(() => {
    const fetchSuggestions = async () => {
      try {
        const res = await fetch(`${getApiUrl()}/api/v1/suggestions/home`);
        if (res.ok) {
          const data = await res.json();
          if (data.suggestions && data.suggestions.length > 0) {
            setHomeSuggestions(data.suggestions);
          }
        }
      } catch (e) {
        console.error("Failed to fetch dynamic home suggestions:", e);
      }
    };
    fetchSuggestions();
  }, []);

  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Sync active thread lens setting
  const handleLensChange = useCallback((newLense: 'comprehensive' | 'audits' | 'council' | 'bills' | 'grants') => {
    setLens(newLense);
    setThreads(prev => prev.map(t => {
      if (t.id === activeThreadId) {
        return { ...t, lens: newLense };
      }
      return t;
    }));
  }, [activeThreadId]);

  // Telemetry init
  useEffect(() => {
    if (typeof window === 'undefined') return;
    
    let anonId = localStorage.getItem('penner_anon_id');
    if (!anonId) {
      anonId = 'anon-' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
      localStorage.setItem('penner_anon_id', anonId);
    }
    
    let sessId = sessionStorage.getItem('penner_sess_id');
    if (!sessId) {
      sessId = 'session-' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
      sessionStorage.setItem('penner_sess_id', sessId);
    }
  }, []);

  // Fetch approved homepage insights
  useEffect(() => {
    const fetchHomeCorrelations = async () => {
      try {
        const res = await fetch(`${getApiUrl()}/api/v1/correlations`);
        if (res.ok) {
          const data = await res.json();
          setHomeCorrelations(data);
        }
      } catch (e) {
        console.error("Failed to fetch correlations:", e);
      }
    };
    fetchHomeCorrelations();
  }, []);

  // Stable Resizing Drag Handlers
  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isResizing.current) return;
    if (e.buttons === 0 || !(e.buttons & 1)) {
      isResizing.current = false;
      setResizing(false);
      mouseUpRef.current?.();
      return;
    }
    const newWidth = window.innerWidth - e.clientX;
    if (newWidth > 240 && newWidth < window.innerWidth * 0.6) {
      document.documentElement.style.setProperty('--explorer-width', `${newWidth}px`);
    }
  }, []);

  const handleMouseUp = useCallback(() => {
    isResizing.current = false;
    setResizing(false);
    document.removeEventListener('mousemove', handleMouseMove);
    document.removeEventListener('mouseup', handleMouseUp);
  }, [handleMouseMove]);

  useEffect(() => {
    mouseUpRef.current = handleMouseUp;
  }, [handleMouseUp]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    setResizing(true);
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [handleMouseMove, handleMouseUp]);

  useEffect(() => {
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  const handleCitationClick = useCallback((cite: { text: string; url: string }, type: 'audit' | 'council' | 'web' | 'bill' | 'grant') => {
    setSelectedDocument({ text: cite.text, url: cite.url, type });
    setExplorerTab('viewer');
  }, []);



  // Auto scroll chat
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [threads, activeThreadId]);

  // Execute conversation search
  const handleSubmit = async (
    e?: React.FormEvent, 
    queryOverride?: string,
    initialDbCitations?: any[],
    initialCitations?: any[]
  ) => {
    if (e) e.preventDefault();
    const userQuery = (queryOverride || query).trim();
    if (!userQuery) return;
    setQuery('');

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

    const userMsg: Message = { role: 'user', content: userQuery };
    const assistantMsg: Message = { 
      role: 'assistant', 
      content: '', 
      loading: true,
      citations: initialCitations || [],
      dbCitations: initialDbCitations || [],
      suggestions: [],
      correlations: []
    };

    setThreads(prev => prev.map(t => {
      if (t.id === currentThreadId) {
        return { ...t, messages: [...t.messages, userMsg, assistantMsg] };
      }
      return t;
    }));

    // Map existing messages to history format
    const history = currentThread 
      ? currentThread.messages.map(m => ({ role: m.role, content: m.content }))
      : [];

    // Reset stream ref
    streamTextRef.current = "";
    if (flushIntervalRef.current) {
      clearInterval(flushIntervalRef.current);
      flushIntervalRef.current = null;
    }

    try {
      const anonHeaders: Record<string, string> = typeof window !== 'undefined' ? {
        'x-anonymous-user-id': localStorage.getItem('penner_anon_id') || 'unknown-user',
        'x-session-id': sessionStorage.getItem('penner_sess_id') || 'unknown-session'
      } : {};

      const response = await fetch(`${getApiUrl()}/api/v1/chat`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          ...anonHeaders
        },
        body: JSON.stringify({ query: userQuery, lens, history })
      });

      if (!response.ok) {
        let errorMsg = `HTTP Error ${response.status}`;
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errorMsg = errData.detail;
          }
        } catch (_) {}
        throw new Error(errorMsg);
      }

      if (!response.body) throw new Error("No stream body");

      // Start the flush interval (every 100ms)
      flushIntervalRef.current = setInterval(() => {
        setThreads(prev => prev.map(t => {
          if (t.id === currentThreadId) {
            const msgs = [...t.messages];
            const lastIdx = msgs.length - 1;
            if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
              if (msgs[lastIdx].content !== streamTextRef.current) {
                msgs[lastIdx] = { ...msgs[lastIdx], content: streamTextRef.current };
              }
            }
            return { ...t, messages: msgs };
          }
          return t;
        }));
      }, 100);

      const reader = response.body.getReader();
      try {
        const decoder = new TextDecoder();
        let streamBuffer = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          streamBuffer += decoder.decode(value, { stream: true });
          const lines = streamBuffer.split('\n');
          streamBuffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith('data:')) {
              const dataStr = trimmed.slice(trimmed.startsWith('data: ') ? 6 : 5).trim();
              if (!dataStr) continue;

              if (dataStr === '[DONE]') {
                break;
              }

              try {
                const data = jsonParseSegment(dataStr);
                if (data.status || data.message) {
                  setThreads(prev => prev.map(t => {
                    if (t.id === currentThreadId) {
                      const msgs = [...t.messages];
                      const lastIdx = msgs.length - 1;
                      if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
                        msgs[lastIdx] = {
                          ...msgs[lastIdx],
                          status: data.status || msgs[lastIdx].status,
                          statusMessage: data.message || msgs[lastIdx].statusMessage
                        };
                      }
                      return { ...t, messages: msgs };
                    }
                    return t;
                  }));
                }
                if (data.chunk) {
                  streamTextRef.current += data.chunk;
                } else if (data.citations || data.db_citations || data.suggestions || data.correlations || data.lens_metadata) {
                  setThreads(prev => prev.map(t => {
                    if (t.id === currentThreadId) {
                      const msgs = [...t.messages];
                      const lastIdx = msgs.length - 1;
                      if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
                        msgs[lastIdx] = {
                          ...msgs[lastIdx],
                          citations: (data.citations && data.citations.length > 0) ? data.citations : msgs[lastIdx].citations,
                          dbCitations: (data.db_citations && data.db_citations.length > 0) ? data.db_citations : msgs[lastIdx].dbCitations,
                          suggestions: (data.suggestions && data.suggestions.length > 0) ? data.suggestions : msgs[lastIdx].suggestions,
                          correlations: (data.correlations && data.correlations.length > 0) ? data.correlations : msgs[lastIdx].correlations,
                          lensMetadata: data.lens_metadata || msgs[lastIdx].lensMetadata
                        };
                      }
                      return { ...t, messages: msgs };
                    }
                    return t;
                  }));
                }
              } catch (err) {
                // Partial JSON parsing issues
              }
            }
          }
        }
      } finally {
        if (flushIntervalRef.current) {
          clearInterval(flushIntervalRef.current);
          flushIntervalRef.current = null;
        }
        try {
          reader.releaseLock();
        } catch (_) {}
        // Guarantee loading: false and final flush of streamTextRef.current
        setThreads(prev => prev.map(t => {
          if (t.id === currentThreadId) {
            const msgs = [...t.messages];
            const lastIdx = msgs.length - 1;
            if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
              msgs[lastIdx] = { 
                ...msgs[lastIdx], 
                content: streamTextRef.current,
                loading: false 
              };
            }
            return { ...t, messages: msgs };
          }
          return t;
        }));
      }
    } catch (e) {
      console.error(e);
      if (flushIntervalRef.current) {
        clearInterval(flushIntervalRef.current);
        flushIntervalRef.current = null;
      }
      setThreads(prev => prev.map(t => {
        if (t.id === currentThreadId) {
          const msgs = [...t.messages];
          const lastIdx = msgs.length - 1;
          if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
            msgs[lastIdx] = { 
              ...msgs[lastIdx], 
              content: e instanceof Error ? e.message : "I encountered an error connecting to the civic database service. Please verify your connection parameters.", 
              loading: false 
            };
          }
          return { ...t, messages: msgs };
        }
        return t;
      }));
    }
  };

  const jsonParseSegment = (str: string) => {
    try {
      return JSON.parse(str);
    } catch (e) {
      return {};
    }
  };

  const handleSuggestionClick = (prompt: string) => {
    setQuery(prompt);
    handleSubmit(undefined, prompt);
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

      const res = await fetch(`${getApiUrl()}/api/v1/auth/assign`, {
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

  // Bug Report Form submission
  const handleBugSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bugDescription.trim()) return;
    setBugStatus('loading');
    
    try {
      const anonHeaders: Record<string, string> = typeof window !== 'undefined' ? {
        'x-anonymous-user-id': localStorage.getItem('penner_anon_id') || 'unknown-user',
        'x-session-id': sessionStorage.getItem('penner_sess_id') || 'unknown-session'
      } : {};
      
      const res = await fetch(`${getApiUrl()}/api/v1/bugs`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          ...anonHeaders
        },
        body: JSON.stringify({
          name: bugName.trim() || 'Citizen User',
          email: bugEmail.trim() || 'anonymous@example.com',
          report_type: bugType,
          description: bugDescription.trim()
        })
      });
      
      if (res.ok) {
        setBugStatus('success');
        setTimeout(() => {
          setShowBugReport(false);
          setBugName('');
          setBugEmail('');
          setBugDescription('');
          setBugStatus('idle');
        }, 3000);
      } else {
        setBugStatus('error');
      }
    } catch (e) {
      setBugStatus('error');
    }
  };

  const activeThread = threads.find(t => t.id === activeThreadId);
  const activeAssistantMessage = activeThread?.messages.filter(m => m.role === 'assistant').slice(-1)[0];
  const activeCorrelations = activeAssistantMessage?.correlations || [];

  return (
    <div className={`h-screen w-screen overflow-hidden relative flex flex-col font-sans antialiased text-mist bg-transparent ${resizing ? 'select-none' : ''}`}>
      {/* Noise overlay and Wave canvas background */}
      <div className="grain-overlay" />
      <WaveCanvas />
      <div className="fixed top-[-20%] left-[-10%] w-[60%] h-[60%] rounded-full bg-evergreen/[0.08] blur-[130px] pointer-events-none z-0" />
      <div className="fixed bottom-[-20%] right-[-10%] w-[60%] h-[60%] rounded-full bg-emerald-600/[0.06] blur-[130px] pointer-events-none z-0" />

      {/* Header */}
      <header className="z-20 border-b border-slate-200/80 bg-white/75 backdrop-blur-md px-6 py-4 flex justify-between items-center relative shrink-0 shadow-sm">
        <button 
          onClick={() => {
            setActiveThreadId(null);
            setThreads([]);
            setLens('comprehensive');
            setExplorerTab('correlations');
            setSelectedDocument(null);
          }}
          className="flex items-center gap-3 text-left focus:outline-none focus:ring-2 focus:ring-evergreen/20 rounded-xl p-1 -m-1 transition-all hover:opacity-90 cursor-pointer"
        >
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-evergreen to-emerald-600 flex items-center justify-center shadow-md font-black text-white text-lg shadow-evergreen/20 shrink-0">P</div>
          <div>
            <h1 className="font-extrabold text-xl tracking-tight text-slate-900 flex items-center gap-1.5">
              PennerAI
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowBetaDisclosure(true);
                }}
                className="text-[9px] font-extrabold uppercase tracking-wider text-emerald-800 bg-emerald-50 hover:bg-emerald-100 px-2 py-0.5 rounded-full border border-emerald-250/50 cursor-pointer transition-colors"
                type="button"
              >
                Beta
              </button>
            </h1>
            <p className="text-[10px] font-medium text-slate-500 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-evergreen shrink-0"></span>
              Washington Policy Graph
            </p>
          </div>
        </button>

        {/* Lenses toggle in header (only shown when thread is active and multiple lenses have results) */}
        {(() => {
          if (!activeThread) return null;
          
          const counts = activeAssistantMessage?.lensMetadata?.counts || { audits: 0, council: 0, bills: 0, grants: 0 };
          const auditsCount = counts.audits || 0;
          const councilCount = counts.council || 0;
          const billsCount = counts.bills || 0;
          const grantsCount = counts.grants || 0;

          const showAuditsLens = auditsCount > 0;
          const showCouncilLens = councilCount > 0;
          const showBillsLens = billsCount > 0;
          const showGrantsLens = grantsCount > 0;

          const activeLensesCount = 
            (showAuditsLens ? 1 : 0) + 
            (showCouncilLens ? 1 : 0) + 
            (showBillsLens ? 1 : 0) + 
            (showGrantsLens ? 1 : 0);

          if (activeLensesCount <= 1) return null;

          return (
            <div className="flex items-center bg-slate-100 p-1 rounded-xl border border-slate-200/60 shadow-[inset_0_1px_2px_rgba(0,0,0,0.03)] gap-1">
              <button 
                onClick={() => handleLensChange('comprehensive')} 
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold tracking-wide transition-all border-none cursor-pointer ${lens === 'comprehensive' ? 'bg-evergreen text-white shadow-sm shadow-evergreen/20' : 'text-slate-500 hover:text-slate-900 bg-transparent'}`}
              >
                <Layers className="w-3.5 h-3.5" />
                <span>Comprehensive</span>
              </button>
              
              {showAuditsLens && (
                <button 
                  onClick={() => handleLensChange('audits')} 
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold tracking-wide transition-all border-none cursor-pointer ${lens === 'audits' ? 'bg-evergreen text-white shadow-sm shadow-evergreen/20' : 'text-slate-500 hover:text-slate-900 bg-transparent'}`}
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  <span>State Audits</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-black ${lens === 'audits' ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-600'}`}>
                    {auditsCount}
                  </span>
                </button>
              )}

              {showCouncilLens && (
                <button 
                  onClick={() => handleLensChange('council')} 
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold tracking-wide transition-all border-none cursor-pointer ${lens === 'council' ? 'bg-evergreen text-white shadow-sm shadow-evergreen/20' : 'text-slate-500 hover:text-slate-900 bg-transparent'}`}
                >
                  <Building className="w-3.5 h-3.5" />
                  <span>Local Council</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-black ${lens === 'council' ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-600'}`}>
                    {councilCount}
                  </span>
                </button>
              )}

              {showBillsLens && (
                <button 
                  onClick={() => handleLensChange('bills')} 
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold tracking-wide transition-all border-none cursor-pointer ${lens === 'bills' ? 'bg-evergreen text-white shadow-sm shadow-evergreen/20' : 'text-slate-500 hover:text-slate-900 bg-transparent'}`}
                >
                  <ShieldAlert className="w-3.5 h-3.5" />
                  <span>State Bills</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-black ${lens === 'bills' ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-600'}`}>
                    {billsCount}
                  </span>
                </button>
              )}

              {showGrantsLens && (
                <button 
                  onClick={() => handleLensChange('grants')} 
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold tracking-wide transition-all border-none cursor-pointer ${lens === 'grants' ? 'bg-evergreen text-white shadow-sm shadow-evergreen/20' : 'text-slate-500 hover:text-slate-900 bg-transparent'}`}
                >
                  <Coins className="w-3.5 h-3.5" />
                  <span>Grants & Funding</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-black ${lens === 'grants' ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-600'}`}>
                    {grantsCount}
                  </span>
                </button>
              )}
            </div>
          );
        })()}

        <div className="flex items-center gap-3">
          <button 
            onClick={() => {
              if (activeThread) {
                setSubTopic(activeThread.messages.find(m => m.role === 'user')?.content || '');
              }
              setShowSubscribe(true);
            }} 
            className="flex items-center gap-2 px-3 py-1.5 bg-slate-100 hover:bg-slate-200/80 rounded-xl text-xs font-bold text-slate-600 hover:text-slate-900 border border-slate-200/60 transition-all cursor-pointer"
          >
            <Bell className="w-3.5 h-3.5 text-evergreen animate-pulse" />
            <span>Alerts</span>
          </button>
          <a 
            href="https://membrane-api.com" 
            target="_blank" 
            rel="noopener noreferrer" 
            className="text-slate-500 hover:text-evergreen transition-colors text-xs font-semibold tracking-wide hidden md:block"
          >
            Powered by Membrane API
          </a>
        </div>
      </header>

      {/* Main Container */}
      <div className="z-10 flex-1 flex overflow-hidden min-h-0 relative">
        
        {/* Sidebar: Message threads (only visible when threads exist) */}
        {threads.length > 0 && (
          <aside className="w-64 border-r border-slate-200/50 bg-white/70 backdrop-blur-xl shrink-0 flex flex-col hidden md:flex z-20">
            <div className="p-4 border-b border-slate-100 bg-slate-50/30">
              <button 
                onClick={() => {
                  setActiveThreadId(null);
                  setExplorerTab('correlations');
                  setSelectedDocument(null);
                }} 
                className="w-full py-3 px-4 bg-evergreen hover:bg-emerald-700 text-white rounded-xl text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-2 cursor-pointer border border-evergreen/10 shadow-md shadow-evergreen/10 hover:shadow-lg hover:shadow-evergreen/20 hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98]"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>New Conversation</span>
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-3 custom-scrollbar space-y-2">
              <div className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-3 pl-2">History</div>
              {threads.map(t => (
                <button
                  key={t.id}
                  onClick={() => {
                    setActiveThreadId(t.id);
                    setLens(t.lens);
                    setSelectedDocument(null);
                    setExplorerTab('correlations');
                  }}
                  className={`w-full text-left p-3 rounded-xl border text-xs leading-relaxed transition-all truncate flex items-center justify-between group cursor-pointer ${
                    t.id === activeThreadId 
                      ? 'bg-white border-slate-200/80 shadow-sm text-evergreen font-black border-l-4 border-l-evergreen' 
                      : 'bg-transparent border-transparent text-slate-500 hover:text-slate-900 hover:bg-white/40 hover:border-slate-200/50 hover:shadow-sm'
                  }`}
                >
                  <span className="truncate pr-2">"{t.title}"</span>
                  <ChevronRight className={`w-3.5 h-3.5 text-slate-400 group-hover:text-evergreen transition-colors ${t.id === activeThreadId ? 'translate-x-0' : '-translate-x-1 opacity-0 group-hover:opacity-100 group-hover:translate-x-0'}`} />
                </button>
              ))}
            </div>

            {/* Sidebar Curation & Tip Actions */}
            <div className="p-4 border-t border-slate-100/80 flex flex-col gap-2 bg-slate-50/30">
              <button 
                onClick={() => {
                  setBugType('bug');
                  setShowBugReport(true);
                }}
                className="w-full py-2.5 px-3 text-slate-650 hover:text-rose-600 hover:bg-rose-50/50 border border-slate-200/80 hover:border-rose-200 rounded-xl text-[9px] font-black uppercase tracking-widest transition-all cursor-pointer glass hover:shadow-sm flex items-center justify-center gap-1.5"
              >
                🐞 Report a Bug
              </button>
              <button 
                onClick={() => {
                  setBugType('tip');
                  setShowBugReport(true);
                }}
                className="w-full py-2.5 px-3 text-slate-650 hover:text-emerald-700 hover:bg-emerald-50/50 border border-slate-200/80 hover:border-emerald-200 rounded-xl text-[9px] font-black uppercase tracking-widest transition-all cursor-pointer glass hover:shadow-sm flex items-center justify-center gap-1.5"
              >
                💡 Submit Civic Tip
              </button>
            </div>
          </aside>
        )}

        {/* Center / Layout Workspace */}
        <div className="flex-1 flex overflow-hidden min-h-0 relative">
          
          {/* Main Chat Column */}
          <div className="flex-1 flex flex-col min-h-0 bg-slate-50/30">
            {/* HERO STATE (Zero Threads) */}
            {!activeThreadId ? (
              <div className="flex-1 overflow-y-auto custom-scrollbar relative z-10 pt-16 pb-16">
                <div className="flex flex-col items-center px-6 max-w-5xl mx-auto w-full text-center">
                  <div className="w-20 h-20 rounded-[2rem] bg-gradient-to-br from-evergreen to-emerald-600 flex items-center justify-center shadow-[0_15px_35px_rgba(12,90,76,0.25)] border border-evergreen/20 mb-8 transform transition-transform hover:scale-105 duration-300 shrink-0">
                    <Sparkles className="w-10 h-10 text-white" />
                  </div>

                  <h2 className="font-serif text-3xl md:text-5xl font-black tracking-tight text-slate-900 mb-4 text-balance shrink-0">
                    Explore Washington <br /> Civic Intelligence
                  </h2>
                  <p className="text-sm md:text-base text-slate-500 mb-8 max-w-lg leading-relaxed font-medium shrink-0">
                    I monitor state audits, city council minutes, and policy files in real-time. Ask any question to map facts and analyze correlations.
                  </p>

                  {/* Main Hero Input Box */}
                  <SearchForm 
                    onSubmit={(q) => handleSubmit(undefined, q)} 
                    placeholder="Ask any question to map facts and analyze correlations..."
                    showTypewriter={true}
                    className="max-w-xl mb-6 shrink-0"
                  />

                  {/* Sample Prompt Chips */}
                  <div className="flex flex-col gap-2.5 justify-center mb-10 w-full max-w-xl shrink-0">
                    {homeSuggestions.map((sugg, idx) => (
                      <button 
                        key={`home-sugg-${idx}`}
                        onClick={() => handleSuggestionClick(sugg)} 
                        className="w-full px-5 py-3 glass hover:bg-white/90 border border-slate-200/80 text-slate-650 hover:text-slate-900 rounded-2xl text-xs font-bold transition-all cursor-pointer shadow-sm flex items-center justify-between group border-none"
                      >
                        <span className="text-left font-semibold">{sugg}</span>
                        <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-evergreen transition-colors" />
                      </button>
                    ))}
                  </div>

                  {/* Surfaced Insights/Correlations Section */}
                  {homeCorrelations.length > 0 && (
                    <div className="w-full mt-4 z-10 animate-fade-in text-left shrink-0">
                      <h3 className="text-xs font-black text-slate-400 uppercase tracking-widest mb-4 pl-2 flex items-center gap-2 font-sans">
                        <Activity className="w-4 h-4 text-evergreen" />
                        <span>Surfaced Governance Insights</span>
                      </h3>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {homeCorrelations.map(corr => (
                          <button
                            key={corr.id}
                            onClick={() => {
                              setSelectedHomeCorr(corr);
                              setShowCorrModal(true);
                            }}
                            className="p-5 rounded-2xl glass hover:bg-white/90 hover:border-evergreen/25 text-left transition-all hover:-translate-y-0.5 hover:shadow-lg group cursor-pointer"
                          >
                            <span className="text-[8px] font-black uppercase tracking-wider text-emerald-800 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                              Proactive Match
                            </span>
                            <h4 className="text-sm font-bold text-slate-900 mt-2 mb-2 group-hover:text-evergreen transition-colors">
                              {corr.title}
                            </h4>
                            <p className="text-xs text-slate-500 leading-relaxed line-clamp-3 font-medium">
                              {corr.hook}
                            </p>
                            <div className="mt-4 flex items-center justify-between text-[10px] text-slate-400 font-bold uppercase tracking-wider">
                              <span>{corr.citations?.length || 0} Citations</span>
                              <span className="text-evergreen group-hover:text-emerald-700 flex items-center gap-1">
                                <span>Explore Report</span>
                                <ChevronRight className="w-3 h-3" />
                              </span>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ) : (
                // ACTIVE CHAT VIEW
                  <div className="flex-1 flex flex-col min-h-0 relative z-10">
                {/* Chat Message Thread */}
                <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
                  <div className="max-w-3xl mx-auto w-full space-y-6">
                    {activeThread?.messages.map((msg, idx) => (
                      <MessageBubble
                        key={idx}
                        msg={msg}
                        idx={idx}
                        lens={lens}
                        handleCitationClick={handleCitationClick}
                        handleSuggestionClick={handleSuggestionClick}
                      />
                    ))}
                  </div>
                </div>

                {/* Bottom Input Area */}
                <div className="p-4 border-t border-slate-200/80 bg-white/75 backdrop-blur-md shrink-0">
                  <SearchForm 
                    onSubmit={(q) => handleSubmit(undefined, q)} 
                    placeholder="Ask a follow up question or specify a new target..."
                    showTypewriter={false}
                    isFollowUp={true}
                    className="max-w-3xl mx-auto"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Dynamic Explorer (Resizable) */}
          {activeThreadId !== null && (
            <>
              {/* Resize handle */}
              <div 
                onMouseDown={handleMouseDown}
                className="w-1.5 h-full cursor-col-resize hover:bg-evergreen/35 active:bg-evergreen/50 transition-colors z-30 relative select-none shrink-0 hidden lg:block bg-slate-200/50"
              />
              <aside 
                style={{ width: 'var(--explorer-width, 320px)' }}
                className="border-l border-slate-200/80 bg-white shrink-0 flex flex-col hidden lg:flex"
              >
                <div className="p-4 border-b border-slate-200/80 flex items-center justify-between shrink-0 bg-slate-50/50">
                  {explorerTab === 'viewer' ? (
                    <button 
                      onClick={() => {
                        setExplorerTab('correlations');
                        setSelectedDocument(null);
                      }}
                      className="text-xs font-black text-slate-500 hover:text-slate-800 transition-colors flex items-center gap-2 cursor-pointer outline-none border-none bg-transparent"
                    >
                      <ArrowLeft className="w-4 h-4 text-evergreen animate-pulse" />
                      <span>Back to Correlations</span>
                    </button>
                  ) : (
                    <h3 className="text-xs font-black text-slate-800 tracking-widest uppercase flex items-center gap-2">
                      <Activity className="w-4 h-4 text-evergreen" />
                      <span>Correlation Explorer</span>
                    </h3>
                  )}
                  <span className="text-[9px] font-black text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full uppercase tracking-wider">pgvector</span>
                </div>

                <div className="flex-1 overflow-y-auto p-4 custom-scrollbar flex flex-col gap-4 min-h-0 bg-slate-50/20">
                  {explorerTab === 'viewer' && selectedDocument ? (
                    <DocumentViewer
                      selectedDocument={selectedDocument}
                      onClose={() => {
                        setExplorerTab('correlations');
                        setSelectedDocument(null);
                      }}
                      resizing={resizing}
                    />
                  ) : (
                    (() => {
                      const filteredCorrelations = activeCorrelations.filter(c => {
                        if (lens === 'comprehensive') return true;
                        if (lens === 'audits') return c.source === 'audit';
                        if (lens === 'council') return c.source === 'council';
                        if (lens === 'bills') return c.source === 'bill';
                        if (lens === 'grants') return c.source === 'grant';
                        return true;
                      });
                      
                      return filteredCorrelations.length > 0 ? (
                        filteredCorrelations.map((c, idx) => (
                          <CorrelationCard
                            key={idx}
                            correlation={c}
                            onClickInvestigate={handleSuggestionClick}
                          />
                        ))
                      ) : (
                        <div className="flex flex-col items-center justify-center text-center py-20 px-4 text-slate-400 space-y-3">
                          <Database className="w-8 h-8 text-slate-300" />
                          <div>
                            <h4 className="text-xs font-bold text-slate-600">No matching correlations</h4>
                            <p className="text-[10px] text-slate-400 mt-1 max-w-[180px] mx-auto leading-relaxed">
                              No pgvector entries match the selected lens filter.
                            </p>
                          </div>
                        </div>
                      );
                    })()
                  )}
                </div>
              </aside>
            </>
          )}

        </div>
      </div>

      <footer className="z-20 border-t border-slate-200/80 bg-white py-4 px-6 text-[10px] font-medium text-slate-500 flex flex-col md:flex-row justify-between items-center gap-3 shrink-0 shadow-sm relative">
        <div className="flex items-center gap-2.5">
          <span className="font-semibold">&copy; 2026 Penner Strategy LLC. All rights reserved.</span>
          <span className="text-slate-300">|</span>
          <button 
            onClick={() => setShowBetaDisclosure(true)} 
            className="text-[10px] font-black text-slate-400 hover:text-evergreen transition-colors uppercase tracking-widest border-none bg-transparent cursor-pointer outline-none"
          >
            Beta Disclaimer
          </button>
        </div>
        
        {!activeThreadId && (
          <div className="md:absolute md:left-1/2 md:-translate-x-1/2 flex items-center gap-4">
            <button 
              onClick={() => {
                setBugType('bug');
                setShowBugReport(true);
              }} 
              className="text-[10px] font-black text-slate-400 hover:text-rose-600 transition-colors uppercase tracking-widest border-none bg-transparent cursor-pointer outline-none"
            >
              Report Bug
            </button>
            <span className="text-slate-300">|</span>
            <button 
              onClick={() => {
                setBugType('tip');
                setShowBugReport(true);
              }} 
              className="text-[10px] font-black text-slate-400 hover:text-evergreen transition-colors uppercase tracking-widest border-none bg-transparent cursor-pointer outline-none"
            >
              Submit Tip
            </button>
          </div>
        )}
        

      </footer>

      {/* Subscription Alerts Modal */}
      {showSubscribe && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm animate-fade-in">
          <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 max-w-md w-full shadow-2xl relative text-slate-800">
            <button 
              onClick={() => {
                setShowSubscribe(false);
                setSubStatus('idle');
              }} 
              className="absolute top-5 right-5 p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-50 rounded-xl transition-all cursor-pointer border border-transparent hover:border-slate-100 outline-none"
              aria-label="Close dialog"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-4 mb-5 text-left">
              <div className="w-12 h-12 rounded-2xl bg-evergreen/5 border border-evergreen/10 flex items-center justify-center text-evergreen shrink-0 shadow-sm">
                <Bell className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <h3 className="text-lg font-black text-slate-900 leading-tight tracking-tight">Create Civic Alert</h3>
                  <span className="text-[9px] font-extrabold uppercase tracking-wider text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-250/50 shrink-0">
                    Beta
                  </span>
                </div>
                <p className="text-xs text-slate-500 font-medium leading-normal">Monitor governance issues and receive email updates when new information emerges.</p>
              </div>
            </div>

            {/* Beta/Development Disclosure Box */}
            <div className="mb-5 p-3.5 bg-amber-50/70 border border-amber-200/85 rounded-2xl flex gap-3 text-left">
              <Info className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <h4 className="text-[10px] font-bold text-amber-900 uppercase tracking-wider">Under Development</h4>
                <p className="text-[10px] text-amber-800/90 leading-relaxed font-semibold">
                  Civic Alerts are currently in preview. We are actively refining our automated monitoring pipeline, so notifications may be delayed or limited during this testing phase.
                </p>
              </div>
            </div>

            {subStatus === 'success' ? (
              <div className="bg-emerald-50/50 border border-emerald-200 p-6 rounded-2xl text-center space-y-3 py-8 text-emerald-900 animate-fade-in">
                <div className="w-12 h-12 rounded-full bg-emerald-100 text-emerald-600 border border-emerald-250 flex items-center justify-center mx-auto text-xl font-bold">
                  ✓
                </div>
                <h4 className="text-xs font-black uppercase tracking-widest">Alert Activated</h4>
                <p className="text-xs font-semibold text-emerald-800 leading-relaxed max-w-xs mx-auto">
                  You have registered for Civic Alerts. We will notify you at <span className="font-bold underline">{subEmail}</span> as soon as new findings surface.
                </p>
              </div>
            ) : (
              <form onSubmit={handleSubscribe} className="space-y-4 text-left">
                <div>
                  <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 pl-0.5">
                    Your Name
                  </label>
                  <input 
                    type="text" 
                    required
                    placeholder="Jane Citizen"
                    className="w-full px-4 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all placeholder-slate-400 shadow-sm"
                    value={subName}
                    onChange={e => setSubName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 pl-0.5">
                    Your Email
                  </label>
                  <input 
                    type="email" 
                    required
                    placeholder="jane@example.com"
                    className="w-full px-4 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all placeholder-slate-400 shadow-sm"
                    value={subEmail}
                    onChange={e => setSubEmail(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 pl-0.5">
                    Topic / Query of Interest
                  </label>
                  <textarea 
                    rows={3}
                    required
                    placeholder="e.g. Bellevue school district audit findings, interfund loan approvals"
                    className="w-full px-4 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all resize-y min-h-[90px] leading-relaxed custom-scrollbar placeholder-slate-400 shadow-sm"
                    value={subTopic}
                    onChange={e => setSubTopic(e.target.value)}
                  />
                </div>

                {subStatus === 'error' && (
                  <p className="text-xs font-bold text-rose-600">Failed to register subscription. Please try again.</p>
                )}

                <button 
                  type="submit" 
                  disabled={subStatus === 'loading'}
                  className="w-full py-3.5 bg-evergreen hover:bg-emerald-850 disabled:bg-evergreen/40 text-white rounded-xl text-xs font-black uppercase tracking-widest shadow-md hover:shadow-lg transition-all active:scale-[0.98] disabled:scale-100 cursor-pointer flex items-center justify-center gap-2 border-none"
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
                <div className="text-center pt-3 mt-1 border-t border-slate-100">
                  <Link 
                    href="/subscribe" 
                    className="inline-flex items-center gap-1 text-[10px] font-black text-slate-450 hover:text-evergreen transition-colors uppercase tracking-widest"
                  >
                    <span>Open Standalone Registration Page</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Surfaced Correlation Report Viewer Modal */}
      {showCorrModal && selectedHomeCorr && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 max-w-2xl w-full shadow-2xl relative flex flex-col max-h-[85vh] overflow-hidden text-slate-800">
            <button 
              onClick={() => {
                setShowCorrModal(false);
                setSelectedHomeCorr(null);
              }} 
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-900 transition-colors cursor-pointer text-sm outline-none font-bold border-none bg-transparent"
            >
              ✕
            </button>

            <div className="flex items-center gap-3.5 mb-6 pb-4 border-b border-slate-100 shrink-0">
              <div className="w-11 h-11 rounded-xl bg-evergreen/10 border border-evergreen/20 flex items-center justify-center text-evergreen">
                <Activity className="w-5.5 h-5.5" />
              </div>
              <div className="min-w-0 flex-1">
                <span className="text-[9px] font-black uppercase text-evergreen tracking-wider">Surfaced Correlation Report</span>
                <h3 className="text-sm md:text-base font-extrabold text-slate-900 truncate leading-snug">{selectedHomeCorr.title}</h3>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar space-y-5 text-left text-xs md:text-sm">
              <div className="p-4 bg-slate-50 border-l-2 border-emerald-500 rounded-r-xl italic text-slate-650 font-medium">
                "{selectedHomeCorr.hook}"
              </div>
              <div className="prose prose-sm max-w-none text-slate-700 leading-relaxed font-medium space-y-4">
                {renderMessageContent(
                  selectedHomeCorr.report_markdown,
                  (selectedHomeCorr.citations || []).map((c: any) => ({
                    text: c.title,
                    url: c.url
                  })),
                  (selectedHomeCorr.citations || []).map((c: any) => ({
                    text: c.title,
                    url: c.url,
                    type: c.source === 'audit' ? 'audit' : c.source === 'council' ? 'council' : c.source === 'bill' ? 'bill' : 'grant'
                  })),
                  handleCitationClick,
                  lens
                )}
              </div>
              
              {/* Citations section */}
              {selectedHomeCorr.citations && selectedHomeCorr.citations.length > 0 && (
                <div className="pt-4 border-t border-slate-100">
                  <h4 className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-3">Supporting Citations ({selectedHomeCorr.citations.length})</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                    {selectedHomeCorr.citations.map((cit: any, cIdx: number) => (
                      <div 
                        key={cIdx}
                        className="p-3 rounded-xl bg-slate-50 border border-slate-200/60 flex items-center justify-between hover:bg-slate-100 transition-colors group"
                      >
                        <div className="min-w-0 pr-2">
                          <span className={`text-[8px] font-black uppercase px-1.5 py-0.2 rounded border ${
                            cit.source === 'audit' ? 'bg-purple-50 text-purple-700 border-purple-200' :
                            cit.source === 'council' ? 'bg-blue-50 text-blue-700 border-blue-200' :
                            cit.source === 'budget' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
                            cit.source === 'grant' ? 'bg-amber-50 text-amber-700 border-amber-250' :
                            cit.source === 'school' ? 'bg-indigo-50 text-indigo-700 border-indigo-200' :
                            cit.source === 'contribution' ? 'bg-rose-50 text-rose-700 border-rose-200' :
                            'bg-teal-50 text-teal-700 border-teal-200'
                          }`}>
                            {cit.source === 'audit' ? 'Audit' :
                             cit.source === 'council' ? 'Council' :
                             cit.source === 'budget' ? 'Budget' :
                             cit.source === 'grant' ? 'Grant' :
                             cit.source === 'school' ? 'School' :
                             cit.source === 'contribution' ? 'Campaign' :
                             'Legislative'}
                          </span>
                          <h5 className="text-[10px] font-extrabold text-slate-800 truncate mt-1">
                            {cit.title}
                          </h5>
                        </div>
                        {cit.url && (
                          <a 
                            href={cit.url} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="w-6.5 h-6.5 rounded-lg border border-slate-200 bg-white flex items-center justify-center shrink-0 text-slate-400 group-hover:text-evergreen group-hover:border-evergreen/30 transition-colors cursor-pointer"
                          >
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="mt-6 pt-4 border-t border-slate-100 flex justify-end gap-3 shrink-0">
              <button 
                onClick={() => {
                  setShowCorrModal(false);
                  const queryStr = `Analyze the correlation report: "${selectedHomeCorr.title}" and explain its policy significance.

CRITICAL CITATION RULE: You MUST provide inline citations in your response using the exact database bracket labels (e.g., [DB-1], [DB-2]) at the end of sentences where facts from them are referenced. These citations will be rendered as interactive links for the user.

Below is the report draft details for context:
Headline: ${selectedHomeCorr.title}
Teaser: ${selectedHomeCorr.hook}
Markdown Content:
${selectedHomeCorr.report_markdown}

Supporting Citations:
${(selectedHomeCorr.citations || []).map((c: any, idx: number) => `[DB-${idx + 1}] ${c.title || c.text} (${c.url})`).join('\n')}
`;
                  const mappedDbCites = (selectedHomeCorr.citations || []).map((c: any) => ({
                    text: c.title || c.text,
                    url: c.url,
                    type: c.source === 'audit' ? 'audit' : c.source === 'council' ? 'council' : c.source === 'bill' ? 'bill' : 'grant'
                  }));
                  const mappedCites = (selectedHomeCorr.citations || []).map((c: any) => ({
                    text: c.title || c.text,
                    url: c.url
                  }));
                  handleSubmit(undefined, queryStr, mappedDbCites, mappedCites);
                  setSelectedHomeCorr(null);
                }}
                className="px-4 py-2.5 bg-evergreen hover:bg-emerald-700 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-evergreen/10 cursor-pointer border-none"
              >
                Investigate Further in Chat
              </button>
              <button 
                onClick={() => {
                  setShowCorrModal(false);
                  setSelectedHomeCorr(null);
                }}
                className="px-4 py-2.5 border border-slate-200 hover:bg-slate-50 text-slate-500 rounded-xl text-xs font-bold transition-colors cursor-pointer bg-white"
              >
                Close Report
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bug Report / Civic Tip Modal */}
      {showBugReport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 max-w-md w-full shadow-2xl relative text-slate-800">
            <button 
              onClick={() => {
                setShowBugReport(false);
                setBugStatus('idle');
              }} 
              className="absolute top-4 right-4 text-slate-400 hover:text-slate-900 transition-colors cursor-pointer text-sm outline-none font-bold border-none bg-transparent"
            >
              ✕
            </button>

            <div className="flex items-center gap-4 mb-6">
              <div className={`w-12 h-12 rounded-2xl flex items-center justify-center border transition-all ${
                bugType === 'bug' 
                  ? 'bg-rose-50 border-rose-200 text-rose-600 font-bold text-xl' 
                  : 'bg-emerald-50 border-emerald-200 text-emerald-600 font-bold text-xl'
              }`}>
                {bugType === 'bug' ? '🐞' : '💡'}
              </div>
              <div>
                <h3 className="text-lg font-extrabold text-slate-900 leading-tight">
                  {bugType === 'bug' ? 'Report Beta Bug' : 'Submit Civic Tip'}
                </h3>
                <p className="text-xs text-slate-450 mt-1">
                  {bugType === 'bug' 
                    ? 'Found an issue? Let us know so we can fix it during beta.' 
                    : "Have suggestions for new datasets or features? We'd love to hear them!"}
                </p>
              </div>
            </div>

            {bugStatus === 'success' ? (
              <div className={`border p-6 rounded-2xl text-center space-y-3 py-8 ${
                bugType === 'bug' 
                  ? 'bg-rose-50/50 border-rose-200/60 text-rose-800' 
                  : 'bg-emerald-50/50 border-emerald-200/60 text-emerald-800'
              }`}>
                <div className="text-2xl">✓</div>
                <h4 className="text-xs font-black uppercase tracking-widest">Submission Received</h4>
                <p className="text-xs font-medium">Thank you for your feedback! Our engineering team will review it shortly.</p>
              </div>
            ) : (
              <form onSubmit={handleBugSubmit} className="space-y-4">
                <div>
                  <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1.5 pl-0.5">
                    Your Name
                  </label>
                  <input 
                    type="text" 
                    placeholder="Jane Citizen"
                    className="w-full px-4.5 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all"
                    value={bugName}
                    onChange={e => setBugName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1.5 pl-0.5">
                    Your Email
                  </label>
                  <input 
                    type="email" 
                    placeholder="jane@example.com"
                    className="w-full px-4.5 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all"
                    value={bugEmail}
                    onChange={e => setBugEmail(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1.5 pl-0.5">
                    Description / Feedback
                  </label>
                  <textarea 
                    rows={4}
                    required
                    placeholder={bugType === 'bug' 
                      ? "Describe the issue, steps to reproduce, or compile error..." 
                      : "Describe city audit targets, state bills, or council records you'd like added..."}
                    className="w-full px-4.5 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all resize-none"
                    value={bugDescription}
                    onChange={e => setBugDescription(e.target.value)}
                  />
                </div>

                {bugStatus === 'error' && (
                  <p className="text-xs font-bold text-rose-600">Failed to submit report. Please verify your connection.</p>
                )}

                <button 
                  type="submit" 
                  disabled={bugStatus === 'loading'}
                  className={`w-full py-3.5 text-white rounded-xl text-xs font-black uppercase tracking-widest shadow-lg transition-all cursor-pointer flex items-center justify-center gap-2 border-none ${
                    bugType === 'bug' 
                      ? 'bg-rose-600 hover:bg-rose-700 shadow-rose-600/10' 
                      : 'bg-evergreen hover:bg-emerald-700 shadow-evergreen/10'
                  }`}
                >
                  {bugStatus === 'loading' ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Submitting...</span>
                    </>
                  ) : (
                    <span>Submit Feedback</span>
                  )}
                </button>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Beta Disclosure Modal */}
      {showBetaDisclosure && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-md animate-fade-in">
          <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 max-w-lg w-full shadow-2xl relative text-slate-800 flex flex-col max-h-[90vh]">
            <button 
              onClick={() => setShowBetaDisclosure(false)} 
              className="absolute top-5 right-5 p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-50 rounded-xl transition-all cursor-pointer border border-transparent hover:border-slate-100 outline-none"
              aria-label="Close disclosure"
            >
              <X className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-4 mb-6 text-left shrink-0">
              <div className="w-12 h-12 rounded-2xl bg-evergreen/5 border border-evergreen/10 flex items-center justify-center text-evergreen shrink-0 shadow-sm">
                <ShieldAlert className="w-6 h-6 animate-pulse" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-0.5">
                  <h3 className="text-lg font-black text-slate-900 leading-tight tracking-tight">Beta Disclosure</h3>
                  <span className="text-[9px] font-extrabold uppercase tracking-wider text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-250/50 shrink-0">
                    Active
                  </span>
                </div>
                <p className="text-xs text-slate-500 font-medium leading-normal">Scope of coverage, AI limitations, and verification protocol.</p>
              </div>
            </div>

            {/* Scrollable details */}
            <div className="flex-1 overflow-y-auto pr-1 space-y-5 text-left custom-scrollbar text-xs md:text-sm font-medium text-slate-650 leading-relaxed">
              <div className="p-4 bg-amber-50/60 border border-amber-200/80 rounded-2xl space-y-2">
                <div className="flex items-center gap-2 text-amber-900 font-bold uppercase tracking-wider text-[10px]">
                  <Info className="w-4 h-4 text-amber-700 shrink-0" />
                  <span>Beta Scope & Data Gaps</span>
                </div>
                <p className="text-amber-800 text-xs font-semibold leading-relaxed">
                  PennerAI is currently in a preview beta stage. The system does not contain every council meeting, board meeting, or commission meeting. Information gaps may exist, and some municipal records or historical files might not be fully indexed.
                </p>
              </div>

              <div className="space-y-2">
                <h4 className="font-extrabold text-slate-900 uppercase tracking-widest text-[10px] pl-0.5 text-evergreen">Proprietary Membrane Technology</h4>
                <p className="text-slate-600 pl-0.5">
                  To achieve high-fidelity civic intelligence, we leverage a proprietary membrane technology designed to prevent hallucinations during database population. We are highly confident in the integrity of the raw facts we have collected.
                </p>
              </div>

              <div className="space-y-2">
                <h4 className="font-extrabold text-slate-900 uppercase tracking-widest text-[10px] pl-0.5 text-rose-600">AI Interpretive Layer Notice</h4>
                <p className="text-slate-600 pl-0.5">
                  While our source database is structured to be reliable, the interpretive layer uses advanced artificial intelligence to synthesize answers and connect related records. The AI layer is not perfect and may make mistakes in interpretation, context, or correlation.
                </p>
              </div>

              <div className="p-4 bg-emerald-50/40 border border-emerald-200/80 rounded-2xl space-y-3">
                <div className="flex items-center gap-2 text-emerald-800 font-bold uppercase tracking-wider text-[10px]">
                  <Database className="w-4 h-4 text-emerald-700 shrink-0" />
                  <span>Independent Verification & DB Access</span>
                </div>
                <p className="text-emerald-800 text-xs font-semibold leading-relaxed">
                  Users are strongly encouraged to verify facts and citations against official municipal reports and state logs. If you would like direct access to the SQL database to perform your own validation, please contact the creator directly.
                </p>
                <div className="pt-1">
                  <a 
                    href="mailto:josh@pennerstrategy.com?subject=PennerAI%20Database%20Access%20Request"
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-evergreen hover:bg-emerald-850 text-white rounded-xl text-xs font-black uppercase tracking-widest transition-all shadow-sm cursor-pointer font-sans"
                  >
                    <span>Email josh@pennerstrategy.com</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </a>
                </div>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-100 flex justify-end shrink-0">
              <button 
                onClick={() => setShowBetaDisclosure(false)}
                className="px-5 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-bold transition-all cursor-pointer border border-slate-200/60 shadow-sm"
              >
                Close Disclosure
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Mobile/Tablet Document Viewer Slider Drawer */}
      <div className="lg:hidden">
        <DocumentViewer
          selectedDocument={selectedDocument}
          onClose={() => {
            setExplorerTab('correlations');
            setSelectedDocument(null);
          }}
          resizing={resizing}
        />
      </div>
    </div>
  );
}
