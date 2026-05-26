'use client';

import React, { useState, useEffect } from 'react';
import { 
  Bell, 
  ArrowLeft, 
  Check, 
  RefreshCw, 
  Layers, 
  BookOpen, 
  Building, 
  ShieldAlert, 
  Coins,
  Info
} from 'lucide-react';
import Link from 'next/link';

export default function SubscribePage() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [topics, setTopics] = useState('');
  const [jurisdiction, setJurisdiction] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');

  // Load existing telemetry details or initialize if not present
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !name.trim() || !topics.trim()) return;
    setStatus('loading');

    try {
      const anonHeaders: Record<string, string> = typeof window !== 'undefined' ? {
        'x-anonymous-user-id': localStorage.getItem('penner_anon_id') || 'unknown-user',
        'x-session-id': sessionStorage.getItem('penner_sess_id') || 'unknown-session',
        'Content-Type': 'application/json'
      } : {
        'Content-Type': 'application/json'
      };

      const payload = {
        name: name.trim(),
        email: email.trim(),
        topics: topics.trim(),
        jurisdiction: jurisdiction.trim() || 'Comprehensive',
        query: query.trim() || null
      };

      const res = await fetch('/api/v1/auth/assign', {
        method: 'POST',
        headers: anonHeaders,
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        setStatus('success');
      } else {
        setStatus('error');
      }
    } catch (err) {
      console.error('Subscription error:', err);
      setStatus('error');
    }
  };

  return (
    <div className="min-h-screen w-screen bg-[#F8FAFC] text-[#0F172A] font-sans relative overflow-x-hidden flex flex-col antialiased">
      {/* Texture & Gradients */}
      <div className="grain-overlay" />
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-gradient-to-bl from-emerald-500/10 via-teal-500/5 to-transparent rounded-full blur-3xl pointer-events-none z-0" />
      <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-gradient-to-tr from-emerald-600/5 via-transparent to-transparent rounded-full blur-3xl pointer-events-none z-0" />

      {/* Header */}
      <header className="z-20 border-b border-slate-200/80 bg-white px-6 py-4 flex justify-between items-center relative shrink-0 shadow-sm">
        <Link 
          href="/" 
          className="flex items-center gap-3 text-left focus:outline-none focus:ring-2 focus:ring-evergreen/20 rounded-xl p-1 -m-1 transition-all hover:opacity-90 cursor-pointer"
        >
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-evergreen to-emerald-600 flex items-center justify-center shadow-md font-black text-white text-lg shadow-evergreen/20 shrink-0">
            P
          </div>
          <div>
            <h1 className="font-extrabold text-xl tracking-tight text-slate-900 flex items-center gap-1.5">
              PennerAI
            </h1>
            <p className="text-[10px] font-medium text-slate-500 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-evergreen shrink-0"></span>
              Washington Policy Graph
            </p>
          </div>
        </Link>

        <Link 
          href="/" 
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200/80 rounded-xl text-xs font-bold text-slate-650 hover:text-slate-900 border border-slate-200/60 transition-all cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Search</span>
        </Link>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 flex items-center justify-center p-4 md:p-8 z-10 relative">
        <div className="w-full max-w-2xl bg-white border border-slate-200/80 shadow-2xl rounded-3xl p-6 md:p-10 relative overflow-hidden transition-all duration-300">
          
          {/* Card Accent Top Line */}
          <div className="absolute top-0 inset-x-0 h-1.5 bg-gradient-to-r from-evergreen to-emerald-500" />
          
          {status === 'success' ? (
            <div className="text-center py-12 px-4 space-y-6 animate-fade-in text-slate-800">
              <div className="w-20 h-20 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-255 flex items-center justify-center mx-auto text-xl font-bold shadow-lg shadow-emerald-500/5">
                ✓
              </div>
              <div className="space-y-2">
                <h2 className="text-2xl font-black text-slate-900 tracking-tight">Active Monitor Registered</h2>
                <p className="text-sm text-slate-500 max-w-md mx-auto leading-relaxed font-semibold">
                  Thank you! We've activated your civic monitor alert request. We will scan new SAO audits and municipal council transcripts, emailing updates immediately to <span className="font-bold text-slate-800 underline">{email}</span>.
                </p>
              </div>
              
              <div className="pt-6 border-t border-slate-100 flex flex-col md:flex-row gap-3 justify-center">
                <Link 
                  href="/" 
                  className="px-6 py-3 bg-evergreen hover:bg-emerald-800 text-white rounded-xl text-xs font-black uppercase tracking-widest transition-all shadow-md shadow-evergreen/10 text-center border-none cursor-pointer"
                >
                  Return to Dashboard
                </Link>
                <button 
                  onClick={() => {
                    setName('');
                    setTopics('');
                    setQuery('');
                    setJurisdiction('');
                    setStatus('idle');
                  }} 
                  className="px-6 py-3 border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 rounded-xl text-xs font-bold transition-all text-center cursor-pointer"
                >
                  Register Another Alert
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-6 text-left">
              {/* Heading */}
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-2xl bg-evergreen/5 border border-evergreen/10 flex items-center justify-center text-evergreen shrink-0 shadow-sm">
                  <Bell className="w-6 h-6 animate-swing" />
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-0.5">
                    <h2 className="text-xl font-black text-slate-900 tracking-tight">Civic Monitor Alert</h2>
                    <span className="text-[9px] font-extrabold uppercase tracking-wider text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-250/50 shrink-0">
                      Beta
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 font-medium leading-relaxed">
                    Set up automatic scanning on Washington State audits, municipal actions, and local policies. We will email you the moment matches surface.
                  </p>
                </div>
              </div>

              {/* Beta/Development Disclosure Box */}
              <div className="p-3.5 bg-amber-50/70 border border-amber-200/85 rounded-2xl flex gap-3">
                <Info className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <h4 className="text-[10px] font-bold text-amber-900 uppercase tracking-wider">Under Development</h4>
                  <p className="text-[10px] text-amber-800/90 leading-relaxed font-semibold">
                    Civic Alerts are currently in preview. We are actively refining our automated monitoring pipeline, so notifications may be delayed or limited during this testing phase.
                  </p>
                </div>
              </div>

              {/* Form */}
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 pl-0.5">
                      Your Name
                    </label>
                    <input 
                      type="text" 
                      required
                      placeholder="Jane Citizen"
                      className="w-full px-4 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all placeholder-slate-400 shadow-sm"
                      value={name}
                      onChange={e => setName(e.target.value)}
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
                      value={email}
                      onChange={e => setEmail(e.target.value)}
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 pl-0.5">
                    Topics of Interest
                  </label>
                  <textarea 
                    rows={3}
                    required
                    placeholder="e.g. Bellevue school district budget deficits, municipal road contract bidding, interfund loan approvals..."
                    className="w-full px-4 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all resize-y min-h-[90px] leading-relaxed custom-scrollbar placeholder-slate-400 shadow-sm"
                    value={topics}
                    onChange={e => setTopics(e.target.value)}
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 pl-0.5">
                      Focus Jurisdiction / Category
                    </label>
                    <input 
                      type="text" 
                      placeholder="e.g. Orting, Bellevue School District, state audits (optional)"
                      className="w-full px-4 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all placeholder-slate-400 shadow-sm"
                      value={jurisdiction}
                      onChange={e => setJurisdiction(e.target.value)}
                    />
                  </div>

                  <div>
                    <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 pl-0.5">
                      Specific Query Keywords (Optional)
                    </label>
                    <input 
                      type="text" 
                      placeholder="e.g. 'findings' or 'interfund'"
                      className="w-full px-4 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all placeholder-slate-400 shadow-sm"
                      value={query}
                      onChange={e => setQuery(e.target.value)}
                    />
                  </div>
                </div>

                {status === 'error' && (
                  <div className="p-3.5 bg-rose-50 border border-rose-100 rounded-xl text-rose-700 text-xs font-bold">
                    Failed to register active monitor. Please check your network and try again.
                  </div>
                )}

                <button 
                  type="submit" 
                  disabled={status === 'loading'}
                  className="w-full py-3.5 bg-evergreen hover:bg-emerald-850 disabled:bg-evergreen/40 text-white rounded-xl text-xs font-black uppercase tracking-widest shadow-md hover:shadow-lg transition-all active:scale-[0.98] disabled:scale-100 cursor-pointer flex items-center justify-center gap-2 border-none"
                >
                  {status === 'loading' ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Saving alerts...</span>
                    </>
                  ) : (
                    <span>Register Active Monitor</span>
                  )}
                </button>
              </form>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
