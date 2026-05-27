'use client';

import React, { useState, useEffect, useRef } from 'react';
import { ArrowRight, Send } from 'lucide-react';

interface SearchFormProps {
  onSubmit: (query: string) => void;
  placeholder?: string;
  showTypewriter?: boolean;
  className?: string;
  isFollowUp?: boolean;
}

export const SearchForm: React.FC<SearchFormProps> = ({
  onSubmit,
  placeholder = "Ask a question...",
  showTypewriter = false,
  className = "",
  isFollowUp = false
}) => {
  const [query, setQuery] = useState('');
  const typewriterRef = useRef<HTMLSpanElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    onSubmit(query.trim());
    setQuery('');
  };

  useEffect(() => {
    if (!showTypewriter) return;

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
        delay = 2500;
      } else if (isDeleting && charIndex === 0) {
        isDeleting = false;
        promptIndex = (promptIndex + 1) % samplePrompts.length;
        delay = 500;
      }

      timer = setTimeout(tick, delay);
    };

    timer = setTimeout(tick, 500);

    return () => {
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [showTypewriter]);

  return (
    <form onSubmit={handleSubmit} className={`w-full relative ${className}`}>
      {isFollowUp ? (
        <div className="flex items-center gap-3 relative">
          <input
            type="text"
            className="w-full py-3.5 px-5 border border-slate-250 bg-slate-50 focus:bg-white focus:border-evergreen rounded-xl outline-none font-semibold text-slate-800 placeholder-slate-400 text-sm shadow-inner transition-colors"
            placeholder={placeholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            type="submit"
            className="p-3 bg-evergreen hover:bg-emerald-700 text-white rounded-xl transition-all cursor-pointer border-none shadow-md"
            aria-label="Send query"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      ) : (
        <>
          <div className="absolute inset-0 bg-evergreen/5 rounded-2xl blur-lg group-focus-within:bg-evergreen/10 transition-all" />
          <div className="relative flex items-center bg-white border-2 border-slate-200 group-focus-within:border-evergreen rounded-2xl overflow-hidden shadow-2xl transition-all pr-3">
            <input
              type="text"
              className="w-full py-4 px-5 bg-transparent border-none outline-none font-semibold text-slate-800 placeholder-transparent text-sm"
              placeholder=""
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {!query && showTypewriter && (
              <div className="absolute left-5 pointer-events-none text-slate-400 font-semibold text-sm flex items-center gap-1">
                <span ref={typewriterRef} />
                <span className="w-1 h-4 bg-evergreen animate-pulse" />
              </div>
            )}
            {!query && !showTypewriter && (
              <div className="absolute left-5 pointer-events-none text-slate-400 font-semibold text-sm">
                {placeholder}
              </div>
            )}
            <button
              type="submit"
              className="p-2.5 bg-evergreen hover:bg-emerald-700 rounded-xl text-white transition-all shadow-md cursor-pointer border-none"
              aria-label="Submit query"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </>
      )}
    </form>
  );
};
