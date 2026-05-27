'use client';

import React from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  loading?: boolean;
  status?: 'intent' | 'searching' | 'correlating' | 'synthesizing';
  statusMessage?: string;
  citations?: Array<{ text: string; url: string }>;
  dbCitations?: Array<{ text: string; url: string; type: 'audit' | 'council' | 'bill' | 'grant' }>;
  suggestions?: string[];
}

interface MessageBubbleProps {
  msg: Message;
  idx: number;
  lens: 'comprehensive' | 'audits' | 'council' | 'bills' | 'grants';
  handleCitationClick: (cite: { text: string; url: string }, type: 'audit' | 'council' | 'web' | 'bill' | 'grant') => void;
  handleSuggestionClick?: (sugg: string) => void;
}


// Simple helper to parse and render bold markdown and citation links
const parseInlineMarkdown = (
  text: string, 
  citations: Array<{ text: string; url: string }> = [],
  dbCitations: Array<{ text: string; url: string; type: 'audit' | 'council' | 'bill' | 'grant' }> = [],
  onCitationClick: (cite: { text: string; url: string }, type: 'audit' | 'council' | 'web' | 'bill' | 'grant') => void,
  activeLens: 'comprehensive' | 'audits' | 'council' | 'bills' | 'grants'
): React.ReactNode => {
  if (!text) return null;
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
              type="button"
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
              type="button"
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
            type="button"
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
      <ul key={key} className="list-disc pl-5 my-2.5 space-y-1.5 text-xs md:text-sm">
        {currentList.map((item, idx) => (
          <li key={idx} className="text-slate-700 font-medium leading-relaxed">
            {parseInlineMarkdown(item, citations, dbCitations, onCitationClick, activeLens)}
          </li>
        ))}
      </ul>
    );
    currentList = [];
    isList = false;
    return rendered;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    
    // Table parser
    if (line.trim().startsWith('|')) {
      if (isList) {
        elements.push(flushList(`list-${i}`));
      }
      isTable = true;
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      currentTable.push(cells);
      continue;
    } else if (isTable) {
      elements.push(flushTable(`table-${i}`));
    }

    // Unordered List parser
    if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
      isList = true;
      currentList.push(line.trim().substring(2));
      continue;
    } else if (isList) {
      elements.push(flushList(`list-${i}`));
    }

    // Headers
    if (line.startsWith('### ')) {
      elements.push(<h4 key={i} className="text-sm font-black text-slate-900 mt-5 mb-2 font-serif uppercase tracking-wider">{parseInlineMarkdown(line.substring(4), citations, dbCitations, onCitationClick, activeLens)}</h4>);
    } else if (line.startsWith('## ')) {
      elements.push(<h3 key={i} className="text-base font-black text-slate-900 mt-6 mb-3 font-serif border-b border-slate-100 pb-1">{parseInlineMarkdown(line.substring(3), citations, dbCitations, onCitationClick, activeLens)}</h3>);
    } else if (line.startsWith('# ')) {
      elements.push(<h2 key={i} className="text-lg font-black text-slate-900 mt-7 mb-4 font-serif">{parseInlineMarkdown(line.substring(2), citations, dbCitations, onCitationClick, activeLens)}</h2>);
    } else if (line.trim()) {
      elements.push(<p key={i} className="text-xs md:text-sm text-slate-700 leading-relaxed font-medium mb-3.5 last:mb-0">{parseInlineMarkdown(line, citations, dbCitations, onCitationClick, activeLens)}</p>);
    } else {
      elements.push(<div key={i} className="h-2" />);
    }
  }

  if (isTable) {
    elements.push(flushTable(`table-end`));
  }
  if (isList) {
    elements.push(flushList(`list-end`));
  }

  return <>{elements}</>;
};

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  msg,
  idx,
  lens,
  handleCitationClick,
  handleSuggestionClick
}) => {
  return (
    <div 
      className={`flex flex-col w-full ${msg.role === 'user' ? 'ml-auto items-end' : 'mr-auto items-start w-full'}`}
    >
      {/* Message Bubble */}
      <div 
        className={`px-5 py-3.5 rounded-2xl text-sm leading-relaxed ${
          msg.role === 'user' 
            ? 'bg-evergreen text-white rounded-br-none shadow-md font-medium max-w-xl' 
            : 'bg-white border border-slate-200/80 text-slate-800 rounded-bl-none w-full shadow-md'
        }`}
      >
        {msg.role === 'user' ? (
          <div className="whitespace-pre-wrap font-medium text-xs md:text-sm text-white">
            {msg.content}
          </div>
        ) : msg.loading && !msg.content ? (
          <div className="py-4 px-2 space-y-4 w-full text-slate-800">
            {/* Active Status Header */}
            <div className="flex items-center gap-2.5">
              <RefreshCw className="w-3.5 h-3.5 animate-spin text-evergreen" />
              <span className="font-extrabold tracking-wide text-xs uppercase text-evergreen">
                {msg.statusMessage || "Querying Membrane Nodes..."}
              </span>
            </div>

            <div className="space-y-2 pt-1">
              {/* Progress bar container */}
              <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden shadow-inner relative">
                <div 
                  className="bg-gradient-to-r from-emerald-500 via-teal-600 to-evergreen h-full rounded-full transition-all duration-700 ease-out shadow-sm"
                  style={{ width: `${
                    msg.status === 'intent' ? 25 :
                    msg.status === 'searching' ? 50 :
                    msg.status === 'correlating' ? 75 :
                    msg.status === 'synthesizing' ? 95 : 10
                  }%` }}
                />
              </div>
              {/* Step labels */}
              <div className="flex justify-between items-center text-[10px] font-bold text-slate-400 px-0.5 font-sans">
                <span className={msg.status === 'intent' ? 'text-evergreen font-black scale-105 transition-all' : ['searching', 'correlating', 'synthesizing'].includes(msg.status || '') ? 'text-emerald-600' : ''}>
                  1. Intent Gate
                </span>
                <span className={msg.status === 'searching' ? 'text-evergreen font-black scale-105 transition-all' : ['correlating', 'synthesizing'].includes(msg.status || '') ? 'text-emerald-600' : ''}>
                  2. DB Search
                </span>
                <span className={msg.status === 'correlating' ? 'text-evergreen font-black scale-105 transition-all' : ['synthesizing'].includes(msg.status || '') ? 'text-emerald-600' : ''}>
                  3. Correlations
                </span>
                <span className={msg.status === 'synthesizing' ? 'text-evergreen font-black scale-105 transition-all' : ''}>
                  4. Synthesis
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-4 font-medium">
            {renderMessageContent(msg.content, msg.citations, msg.dbCitations, handleCitationClick, lens)}
            {msg.loading && (
              <div className="flex items-center gap-2 pt-2.5 border-t border-slate-100 mt-3 text-slate-400">
                <RefreshCw className="w-3 h-3 animate-spin text-evergreen" />
                <span className="text-[10px] font-bold uppercase tracking-wider text-evergreen animate-pulse">
                  {msg.statusMessage || "Synthesizing response..."}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Metadata Citations */}
      {!msg.loading && msg.role === 'assistant' && (
        <div className="mt-3 space-y-4 w-full">
          {/* Web Citations */}
          {msg.citations && msg.citations.length > 0 && (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-[9px] font-black text-slate-400 uppercase tracking-widest mr-1.5">Sources:</span>
              {msg.citations.map((cite, cIdx) => (
                <button 
                  key={cIdx} 
                  onClick={() => handleCitationClick(cite, 'web')}
                  className="px-2.5 py-1 bg-white hover:bg-slate-50 border border-slate-200/80 hover:border-slate-300 text-slate-600 hover:text-slate-900 rounded-full text-[11px] font-bold flex items-center gap-1 transition-all cursor-pointer shadow-sm border-none"
                  title={cite.url}
                  type="button"
                >
                  <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[8px] font-black bg-slate-100 text-slate-600 rounded-full border border-slate-200">
                    {cIdx + 1}
                  </span>
                  <span className="max-w-[150px] truncate">{cite.text}</span>
                  <ExternalLink className="w-2.5 h-2.5 text-slate-400" />
                </button>
              ))}
            </div>
          )}

          {/* Database Citations */}
          {msg.dbCitations && msg.dbCitations.length > 0 && (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-[9px] font-black text-slate-400 uppercase tracking-widest mr-1.5">Verified Database:</span>
              {msg.dbCitations.map((cite, cIdx) => {
                let isDimmed = false;
                if (lens !== 'comprehensive') {
                  if (lens === 'audits' && cite.type !== 'audit') isDimmed = true;
                  else if (lens === 'council' && cite.type !== 'council') isDimmed = true;
                  else if (lens === 'bills' && cite.type !== 'bill') isDimmed = true;
                  else if (lens === 'grants' && cite.type !== 'grant') isDimmed = true;
                }
                
                let colorClass = "bg-purple-50 hover:bg-purple-100/80 border-purple-200 text-purple-800";
                if (cite.type === 'council') {
                  colorClass = "bg-blue-50 hover:bg-blue-100/80 border-blue-200 text-blue-800";
                } else if (cite.type === 'bill') {
                  colorClass = "bg-rose-50 hover:bg-rose-100/80 border-rose-200 text-rose-800";
                } else if (cite.type === 'grant') {
                  colorClass = "bg-emerald-50 hover:bg-emerald-100/80 border-emerald-200 text-emerald-800";
                }

                return (
                  <button 
                    key={cIdx} 
                    onClick={() => handleCitationClick(cite, cite.type)}
                    className={`px-2.5 py-1 ${colorClass} border rounded-lg text-[11px] font-bold flex items-center gap-1.5 transition-all cursor-pointer shadow-sm ${isDimmed ? 'opacity-25' : ''}`}
                    title={cite.url}
                    type="button"
                  >
                    <span className="inline-flex items-center justify-center px-1 text-[8px] font-black border rounded bg-white/70">
                      DB-{cIdx + 1}
                    </span>
                    <span className="max-w-[150px] truncate">{cite.text}</span>
                    <ExternalLink className="w-2.5 h-2.5 opacity-60" />
                  </button>
                );
              })}
            </div>
          )}

          {/* Quick action suggestion chips */}
          {msg.suggestions && msg.suggestions.length > 0 && handleSuggestionClick && (
            <div className="flex flex-wrap gap-2">
              {msg.suggestions.map((sugg, sIdx) => (
                <button 
                  key={sIdx} 
                  onClick={() => handleSuggestionClick(sugg)}
                  className="px-3 py-1.5 bg-evergreen/5 hover:bg-evergreen/10 border border-evergreen/10 hover:border-evergreen/20 text-evergreen hover:text-emerald-800 rounded-lg text-xs font-bold transition-all cursor-pointer border-none"
                  type="button"
                >
                  {sugg}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
