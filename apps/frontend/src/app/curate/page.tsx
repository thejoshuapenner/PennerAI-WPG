'use client';

import React, { useState, useEffect } from 'react';
import { 
  Check, 
  X, 
  Edit2, 
  Save, 
  RefreshCw, 
  ArrowLeft, 
  ExternalLink, 
  Activity, 
  FileText, 
  Lock, 
  CheckCircle2, 
  AlertCircle,
  Plus,
  Bug,
  Megaphone,
  Globe,
  Settings,
  Link2,
  AlertTriangle,
  Play,
  Database,
  Volume2,
  Video,
  MessageSquare
} from 'lucide-react';
import Link from 'next/link';

type Citation = {
  id: string;
  source: 'audit' | 'council';
  title: string;
  url: string;
  verbatim_text_context?: string;
  meeting_type?: string;
  verification_score?: number;
  reviewer_status?: string;
};

type Correlation = {
  id: number;
  title: string;
  hook: string;
  report_markdown: string;
  citations: Citation[];
  status: 'proposed' | 'approved' | 'dismissed';
  created_at: string;
  reviewed_at: string | null;
};

type BugReport = {
  id: number;
  name: string | null;
  email: string | null;
  report_type: 'bug' | 'tip';
  description: string;
  anonymous_user_id: string;
  session_id: string;
  created_at: string;
};

type AlertSubscription = {
  id: number;
  name: string;
  email: string;
  topics: string;
  jurisdiction: string | null;
  query: string | null;
  anonymous_user_id: string | null;
  created_at: string;
};

type Entity = {
  id: number;
  name: string;
  entity_type: string;
  official_url: string;
  agenda_portal_url: string | null;
  platform: string | null;
  verification_status: string;
  is_active: boolean;
  minutes_url?: string | null;
  agenda_url?: string | null;
  packets_url?: string | null;
  video_url?: string | null;
  audio_url?: string | null;
  transcripts_url?: string | null;
  crawler_path_filter?: string | null;
  crawler_doc_types?: string | null;
};

const getApiUrl = () => {
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return 'http://localhost:8002';
    }
  }
  return process.env.NEXT_PUBLIC_API_URL || 'https://late-ways-open.loca.lt';
};

export default function CuratePage() {
  const [code, setCode] = useState<string>('');
  const [authorized, setAuthorized] = useState<boolean>(false);
  const [authError, setAuthError] = useState<string>('');
  
  const [correlations, setCorrelations] = useState<Correlation[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [genLoading, setGenLoading] = useState<boolean>(false);
  
  // Dashboard Tabs, Bug reports, and Alerts state
  const [activeTab, setActiveTab] = useState<'correlations' | 'bugs' | 'alerts' | 'entities' | 'sources'>('correlations');
  const [bugReports, setBugReports] = useState<BugReport[]>([]);
  const [selectedBugId, setSelectedBugId] = useState<number | null>(null);
  const [alertSubscriptions, setAlertSubscriptions] = useState<AlertSubscription[]>([]);
  const [selectedAlertId, setSelectedAlertId] = useState<number | null>(null);
  const [sources, setSources] = useState<any[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [loadingSources, setLoadingSources] = useState<boolean>(false);

  // Entities catalog state
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null);
  const [searchEntityQuery, setSearchEntityQuery] = useState<string>('');
  const [filterEntityType, setFilterEntityType] = useState<string>('all');
  
  // Add new entity form state
  const [showAddEntity, setShowAddEntity] = useState<boolean>(false);
  const [newEntityName, setNewEntityName] = useState<string>('');
  const [newEntityType, setNewEntityType] = useState<string>('school_district');
  const [newEntityUrl, setNewEntityUrl] = useState<string>('');
  const [newEntityPortal, setNewEntityPortal] = useState<string>('');
  const [newEntityPlatform, setNewEntityPlatform] = useState<string>('Generic Crawler');
  const [newEntityMinutesUrl, setNewEntityMinutesUrl] = useState<string>('');
  const [newEntityAgendaUrl, setNewEntityAgendaUrl] = useState<string>('');
  const [newEntityPacketsUrl, setNewEntityPacketsUrl] = useState<string>('');
  const [newEntityVideoUrl, setNewEntityVideoUrl] = useState<string>('');
  const [newEntityAudioUrl, setNewEntityAudioUrl] = useState<string>('');
  const [newEntityTranscriptsUrl, setNewEntityTranscriptsUrl] = useState<string>('');
  const [newEntityCrawlPathFilter, setNewEntityCrawlPathFilter] = useState<string>('');
  const [newEntityCrawlDocTypes, setNewEntityCrawlDocTypes] = useState<string[]>(['Minutes']);

  // Edit entity settings
  const [isEditingEntity, setIsEditingEntity] = useState<boolean>(false);
  const [editEntityUrl, setEditEntityUrl] = useState<string>('');
  const [editEntityPortal, setEditEntityPortal] = useState<string>('');
  const [editEntityPlatform, setEditEntityPlatform] = useState<string>('');
  const [editEntityActive, setEditEntityActive] = useState<boolean>(true);
  const [editEntityMinutesUrl, setEditEntityMinutesUrl] = useState<string>('');
  const [editEntityAgendaUrl, setEditEntityAgendaUrl] = useState<string>('');
  const [editEntityPacketsUrl, setEditEntityPacketsUrl] = useState<string>('');
  const [editEntityVideoUrl, setEditEntityVideoUrl] = useState<string>('');
  const [editEntityAudioUrl, setEditEntityAudioUrl] = useState<string>('');
  const [editEntityTranscriptsUrl, setEditEntityTranscriptsUrl] = useState<string>('');
  const [editEntityCrawlPathFilter, setEditEntityCrawlPathFilter] = useState<string>('');
  const [editEntityCrawlDocTypes, setEditEntityCrawlDocTypes] = useState<string[]>(['Minutes']);

  // Crawler trigger form state
  const [crawlUrl, setCrawlUrl] = useState<string>('');
  const [crawlDocTypes, setCrawlDocTypes] = useState<string[]>(['Minutes']);
  const [crawlPlatform, setCrawlPlatform] = useState<string>('Generic Crawler');
  const [crawlPathFilter, setCrawlPathFilter] = useState<string>('');
  
  // Edit State for Correlations
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [editTitle, setEditTitle] = useState<string>('');
  const [editHook, setEditHook] = useState<string>('');
  const [editMarkdown, setEditMarkdown] = useState<string>('');

  // 1. Authorization checks on mount
  useEffect(() => {
    if (typeof window === 'undefined') return;
    
    // Check URL params first
    const params = new URLSearchParams(window.location.search);
    const urlCode = params.get('code');
    const savedCode = localStorage.getItem('penner_admin_code');
    
    const activeCode = urlCode || savedCode;
    if (activeCode) {
      verifyCodeAndFetch(activeCode);
    } else {
      setLoading(false);
    }
  }, []);

  const verifyCodeAndFetch = async (inputCode: string) => {
    setLoading(true);
    setAuthError('');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/correlations/admin?code=${inputCode}`);
      if (res.ok) {
        const data = await res.json();
        setCorrelations(data);
        localStorage.setItem('penner_admin_code', inputCode);
        setCode(inputCode);
        setAuthorized(true);
        if (data.length > 0) {
          selectCorrelation(data[0]);
        }
        // Fetch remaining admin datasets
        fetchBugReports(inputCode);
        fetchAlertSubscriptions(inputCode);
        fetchEntities(inputCode);
        fetchSources(inputCode);
      } else {
        localStorage.removeItem('penner_admin_code');
        setAuthError('Invalid admin access code.');
        setAuthorized(false);
      }
    } catch (e) {
      setAuthError('Connection failed. Verify your backend is running.');
      setAuthorized(false);
    } finally {
      setLoading(false);
    }
  };

  const handleAuthSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (code.trim()) {
      verifyCodeAndFetch(code.trim());
    }
  };

  const selectCorrelation = (c: Correlation) => {
    setSelectedId(c.id);
    setEditTitle(c.title);
    setEditHook(c.hook);
    setEditMarkdown(c.report_markdown);
    setIsEditing(false);
  };

  const selectEntity = (e: Entity) => {
    setSelectedEntityId(e.id);
    setEditEntityUrl(e.official_url);
    setEditEntityPortal(e.agenda_portal_url || '');
    setEditEntityPlatform(e.platform || 'Generic Crawler');
    setEditEntityActive(e.is_active);
    setEditEntityMinutesUrl(e.minutes_url || '');
    setEditEntityAgendaUrl(e.agenda_url || '');
    setEditEntityPacketsUrl(e.packets_url || '');
    setEditEntityVideoUrl(e.video_url || '');
    setEditEntityAudioUrl(e.audio_url || '');
    setEditEntityTranscriptsUrl(e.transcripts_url || '');
    setEditEntityCrawlPathFilter(e.crawler_path_filter || '');
    setEditEntityCrawlDocTypes(e.crawler_doc_types ? e.crawler_doc_types.split(',') : ['Minutes']);
    setIsEditingEntity(false);
    setShowAddEntity(false);
    
    // Auto fill crawl trigger URL
    setCrawlUrl(e.agenda_portal_url || e.official_url);
    setCrawlPlatform(e.platform || 'Generic Crawler');
    setCrawlPathFilter(e.crawler_path_filter || '');
    setCrawlDocTypes(e.crawler_doc_types ? e.crawler_doc_types.split(',') : ['Minutes']);
  };

  const fetchCorrelations = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/correlations/admin?code=${code}`);
      if (res.ok) {
        const data = await res.json();
        setCorrelations(data);
        if (selectedId && !data.find((item: Correlation) => item.id === selectedId)) {
          if (data.length > 0) selectCorrelation(data[0]);
          else setSelectedId(null);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const fetchBugReports = async (inputCode?: string) => {
    const activeCode = inputCode || code;
    if (!activeCode) return;
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/bugs/admin?code=${activeCode}`);
      if (res.ok) {
        const data = await res.json();
        setBugReports(data);
        if (data.length > 0 && !selectedBugId) {
          setSelectedBugId(data[0].id);
        }
      }
    } catch (e) {
      console.error("Failed to fetch bug reports:", e);
    }
  };

  const handleDeleteBug = async (id: number) => {
    setActionLoading('deleting_bug');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/bugs/${id}?code=${code}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        const currentIndex = bugReports.findIndex(b => b.id === id);
        const updatedBugs = bugReports.filter(b => b.id !== id);
        setBugReports(updatedBugs);
        
        if (updatedBugs.length > 0) {
          const nextIndex = currentIndex === bugReports.length - 1 ? currentIndex - 1 : currentIndex;
          setSelectedBugId(updatedBugs[Math.max(0, nextIndex)].id);
        } else {
          setSelectedBugId(null);
        }
      }
    } catch (e) {
      console.error("Failed to delete bug report:", e);
    } finally {
      setActionLoading(null);
    }
  };

  const fetchAlertSubscriptions = async (inputCode?: string) => {
    const activeCode = inputCode || code;
    if (!activeCode) return;
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/alerts/admin?code=${activeCode}`);
      if (res.ok) {
        const data = await res.json();
        setAlertSubscriptions(data);
        if (data.length > 0 && !selectedAlertId) {
          setSelectedAlertId(data[0].id);
        }
      }
    } catch (e) {
      console.error("Failed to fetch alert subscriptions:", e);
    }
  };

  const handleDeleteAlert = async (id: number) => {
    setActionLoading('deleting_alert');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/alerts/${id}?code=${code}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        const currentIndex = alertSubscriptions.findIndex(a => a.id === id);
        const updatedAlerts = alertSubscriptions.filter(a => a.id !== id);
        setAlertSubscriptions(updatedAlerts);
        
        if (updatedAlerts.length > 0) {
          const nextIndex = currentIndex === alertSubscriptions.length - 1 ? currentIndex - 1 : currentIndex;
          setSelectedAlertId(updatedAlerts[Math.max(0, nextIndex)].id);
        } else {
          setSelectedAlertId(null);
        }
      }
    } catch (e) {
      console.error("Failed to delete alert subscription:", e);
    } finally {
      setActionLoading(null);
    }
  };

  const fetchEntities = async (inputCode?: string) => {
    const activeCode = inputCode || code;
    if (!activeCode) return;
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/entities/admin?code=${activeCode}`);
      if (res.ok) {
        const data = await res.json();
        setEntities(data);
        if (data.length > 0 && !selectedEntityId) {
          selectEntity(data[0]);
        }
      }
    } catch (e) {
      console.error("Failed to fetch entities catalog:", e);
    }
  };

  const fetchSources = async (inputCode?: string) => {
    const activeCode = inputCode || code;
    if (!activeCode) return;
    setLoadingSources(true);
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/admin/sources?code=${activeCode}`);
      if (res.ok) {
        const result = await res.json();
        if (result.status === 'success') {
          setSources(result.data);
          if (result.data.length > 0 && !selectedSourceId) {
            setSelectedSourceId(result.data[0].id);
          }
        }
      }
    } catch (e) {
      console.error("Failed to fetch database sources:", e);
    } finally {
      setLoadingSources(false);
    }
  };

  const handleVerifyEntity = async (id: number) => {
    setActionLoading('verifying_entity');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/entities/${id}/verify?code=${code}`, {
        method: 'POST'
      });
      if (res.ok) {
        setEntities(prev => prev.map(e => e.id === id ? { ...e, verification_status: 'verified' } : e));
      }
    } catch (e) {
      console.error("Failed to verify entity official URL:", e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleEditEntity = async (id: number) => {
    setActionLoading('editing_entity');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/entities/${id}/edit?code=${code}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          official_url: editEntityUrl,
          agenda_portal_url: editEntityPortal,
          platform: editEntityPlatform,
          is_active: editEntityActive,
          minutes_url: editEntityMinutesUrl || null,
          agenda_url: editEntityAgendaUrl || null,
          packets_url: editEntityPacketsUrl || null,
          video_url: editEntityVideoUrl || null,
          audio_url: editEntityAudioUrl || null,
          transcripts_url: editEntityTranscriptsUrl || null,
          crawler_path_filter: editEntityCrawlPathFilter || null,
          crawler_doc_types: editEntityCrawlDocTypes.join(',')
        })
      });
      if (res.ok) {
        setEntities(prev => prev.map(e => e.id === id ? { 
          ...e, 
          official_url: editEntityUrl,
          agenda_portal_url: editEntityPortal,
          platform: editEntityPlatform,
          is_active: editEntityActive,
          minutes_url: editEntityMinutesUrl || null,
          agenda_url: editEntityAgendaUrl || null,
          packets_url: editEntityPacketsUrl || null,
          video_url: editEntityVideoUrl || null,
          audio_url: editEntityAudioUrl || null,
          transcripts_url: editEntityTranscriptsUrl || null,
          crawler_path_filter: editEntityCrawlPathFilter || null,
          crawler_doc_types: editEntityCrawlDocTypes.join(',')
        } : e));
        setIsEditingEntity(false);
      }
    } catch (e) {
      console.error("Failed to save entity settings:", e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleAddEntity = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newEntityName || !newEntityUrl) return;
    setActionLoading('adding_entity');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/entities/admin?code=${code}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newEntityName,
          entity_type: newEntityType,
          official_url: newEntityUrl,
          agenda_portal_url: newEntityPortal || null,
          platform: newEntityPlatform,
          minutes_url: newEntityMinutesUrl || null,
          agenda_url: newEntityAgendaUrl || null,
          packets_url: newEntityPacketsUrl || null,
          video_url: newEntityVideoUrl || null,
          audio_url: newEntityAudioUrl || null,
          transcripts_url: newEntityTranscriptsUrl || null,
          crawler_path_filter: newEntityCrawlPathFilter || null,
          crawler_doc_types: newEntityCrawlDocTypes.join(',')
        })
      });
      if (res.ok) {
        const result = await res.json();
        const addedEntity: Entity = {
          id: result.id,
          name: newEntityName,
          entity_type: newEntityType,
          official_url: newEntityUrl,
          agenda_portal_url: newEntityPortal || null,
          platform: newEntityPlatform,
          verification_status: 'verified',
          is_active: true,
          minutes_url: newEntityMinutesUrl || null,
          agenda_url: newEntityAgendaUrl || null,
          packets_url: newEntityPacketsUrl || null,
          video_url: newEntityVideoUrl || null,
          audio_url: newEntityAudioUrl || null,
          transcripts_url: newEntityTranscriptsUrl || null,
          crawler_path_filter: newEntityCrawlPathFilter || null,
          crawler_doc_types: newEntityCrawlDocTypes.join(',')
        };
        setEntities(prev => [addedEntity, ...prev]);
        selectEntity(addedEntity);
        setShowAddEntity(false);
        setNewEntityName('');
        setNewEntityUrl('');
        setNewEntityPortal('');
        setNewEntityMinutesUrl('');
        setNewEntityAgendaUrl('');
        setNewEntityPacketsUrl('');
        setNewEntityVideoUrl('');
        setNewEntityAudioUrl('');
        setNewEntityTranscriptsUrl('');
        setNewEntityCrawlPathFilter('');
        setNewEntityCrawlDocTypes(['Minutes']);
      }
    } catch (e) {
      console.error("Failed to add new entity:", e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleTriggerCrawl = async () => {
    if (!crawlUrl) return;
    setActionLoading('triggering_crawl');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/crawler/trigger?code=${code}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: crawlUrl,
          doc_types: crawlDocTypes,
          platform: crawlPlatform,
          path_filters: crawlPathFilter || null
        })
      });
      if (res.ok) {
        alert(`Custom crawl task queued successfully for ${crawlUrl} using driver ${crawlPlatform}!`);
      }
    } catch (e) {
      console.error("Failed to trigger crawl:", e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleApprove = async (id: number) => {
    setActionLoading('approving');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/correlations/${id}/approve?code=${code}`, {
        method: 'POST'
      });
      if (res.ok) {
        setCorrelations(prev => prev.map(c => c.id === id ? { ...c, status: 'approved' } : c));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDismiss = async (id: number) => {
    setActionLoading('dismissing');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/correlations/${id}/dismiss?code=${code}`, {
        method: 'POST'
      });
      if (res.ok) {
        const currentIndex = correlations.findIndex(c => c.id === id);
        setCorrelations(prev => prev.filter(c => c.id !== id));
        if (correlations.length > 1) {
          const nextIndex = currentIndex === correlations.length - 1 ? currentIndex - 1 : currentIndex + 1;
          selectCorrelation(correlations[nextIndex]);
        } else {
          setSelectedId(null);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleSaveChanges = async (id: number) => {
    setActionLoading('saving');
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/correlations/${id}/edit?code=${code}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: editTitle,
          hook: editHook,
          report_markdown: editMarkdown
        })
      });
      if (res.ok) {
        setCorrelations(prev => prev.map(c => c.id === id ? { 
          ...c, 
          title: editTitle, 
          hook: editHook, 
          report_markdown: editMarkdown 
        } : c));
        setIsEditing(false);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleTriggerGenerate = async () => {
    setGenLoading(true);
    try {
      const res = await fetch(`${getApiUrl()}/api/v1/correlations/generate?code=${code}`, {
        method: 'POST'
      });
      if (res.ok) {
        alert("Correlation generation scheduled in backend background task. Wait a moment and click Refresh.");
      }
    } catch (e) {
      alert("Failed to reach generation backend.");
    } finally {
      setGenLoading(false);
    }
  };

  const activeCorr = correlations.find(c => c.id === selectedId);
  const activeBug = bugReports.find(b => b.id === selectedBugId);
  const activeAlert = alertSubscriptions.find(a => a.id === selectedAlertId);
  const activeEntity = entities.find(e => e.id === selectedEntityId);
  const activeSource = sources.find(s => s.id === selectedSourceId);

  // Filtered entities selector
  const filteredEntities = entities.filter(ent => {
    const matchesSearch = ent.name.toLowerCase().includes(searchEntityQuery.toLowerCase()) || 
                          (ent.official_url && ent.official_url.toLowerCase().includes(searchEntityQuery.toLowerCase()));
    const matchesType = filterEntityType === 'all' || ent.entity_type === filterEntityType;
    return matchesSearch && matchesType;
  });

  // Unauthorized Form View
  if (!authorized) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-obsidian text-mist font-sans p-4 relative overflow-hidden">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] bg-gradient-to-tr from-emerald-950/20 via-teal-900/10 to-transparent rounded-full blur-3xl pointer-events-none" />
        <div className="grain-overlay" />
        
        <div className="w-full max-w-md bg-white border border-slate-200 shadow-2xl rounded-3xl p-8 relative z-10 text-slate-800 text-center">
          <div className="w-16 h-16 rounded-[1.5rem] bg-gradient-to-br from-evergreen to-emerald-600 flex items-center justify-center shadow-lg border border-evergreen/10 mb-6 mx-auto shadow-evergreen/20">
            <Lock className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-black text-slate-900 tracking-tight mb-2">Admin Curation Coda</h1>
          <p className="text-xs text-slate-500 font-medium mb-6">Enter your API key or dashboard access credential to review surfaced correlations.</p>
          
          <form onSubmit={handleAuthSubmit} className="space-y-4 text-left">
            <div>
              <label className="block text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1.5 pl-0.5">Access Code</label>
              <input 
                type="password"
                required
                className="w-full px-4.5 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-2xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all shadow-inner"
                placeholder="sk-penner-..."
                value={code}
                onChange={e => setCode(e.target.value)}
              />
            </div>
            
            {authError && (
              <div className="p-3 bg-rose-50 border border-rose-100 rounded-xl flex items-center gap-2 text-rose-700 text-xs font-semibold">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{authError}</span>
              </div>
            )}
            
            <button 
              type="submit" 
              disabled={loading}
              className="w-full py-3 bg-evergreen hover:bg-emerald-700 text-white rounded-2xl font-bold text-xs tracking-wider uppercase transition-all shadow-md shadow-evergreen/10 cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Authenticate Access'}
            </button>
          </form>
          
          <div className="mt-8 pt-4 border-t border-slate-100">
            <Link href="/" className="text-xs text-slate-400 hover:text-evergreen font-bold flex items-center gap-1.5 justify-center transition-colors">
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to home search</span>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Authorized Dashboard View
  return (
    <div className="h-screen w-screen flex flex-col bg-slate-50/70 font-sans text-slate-800 antialiased overflow-hidden relative">
      <div className="grain-overlay" />
      
      {/* Header */}
      <header className="z-20 border-b border-slate-200/80 bg-white px-6 py-4 flex justify-between items-center relative shrink-0 shadow-sm">
        <div className="flex items-center gap-3">
          <Link 
            href="/"
            className="w-8 h-8 rounded-lg bg-slate-100 hover:bg-slate-200/80 flex items-center justify-center transition-all cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4 text-slate-600" />
          </Link>
          <div>
            <h1 className="font-extrabold text-lg text-slate-900 tracking-tight flex items-center gap-2">
              <Activity className="w-5 h-5 text-emerald-600" />
              <span>Correlation Curation Queue</span>
            </h1>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
              Human-in-the-loop publisher
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          <button 
            onClick={handleTriggerGenerate} 
            disabled={genLoading}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-br from-evergreen to-emerald-600 hover:from-emerald-700 hover:to-emerald-800 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-evergreen/10 cursor-pointer disabled:opacity-50"
          >
            {genLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            <span>Trigger AI Engine</span>
          </button>
          
          <button 
            onClick={() => { fetchCorrelations(); fetchBugReports(); fetchAlertSubscriptions(); fetchEntities(); fetchSources(); }} 
            disabled={loading}
            className="w-9 h-9 border border-slate-200 bg-white hover:bg-slate-100 rounded-xl flex items-center justify-center transition-colors cursor-pointer"
            title="Refresh List"
          >
            <RefreshCw className={`w-4 h-4 text-slate-500 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      {/* Main Body Columns */}
      <div className="flex-1 flex overflow-hidden min-h-0 relative z-10">
        
        {/* Left Column: List Queue */}
        <aside className="w-80 border-r border-slate-200 bg-white shrink-0 flex flex-col">
          <div className="border-b border-slate-200 bg-slate-50/50 flex flex-wrap">
            <button
              onClick={() => setActiveTab('correlations')}
              className={`flex-1 py-3 px-0.5 text-center text-[8px] font-black uppercase tracking-wider border-b-2 transition-all cursor-pointer ${activeTab === 'correlations' ? 'border-evergreen text-evergreen bg-white' : 'border-transparent text-slate-400 hover:text-slate-700'}`}
            >
              Corrs ({correlations.length})
            </button>
            <button
              onClick={() => setActiveTab('entities')}
              className={`flex-1 py-3 px-0.5 text-center text-[8px] font-black uppercase tracking-wider border-b-2 transition-all cursor-pointer ${activeTab === 'entities' ? 'border-blue-500 text-blue-600 bg-white' : 'border-transparent text-slate-400 hover:text-slate-700'}`}
            >
              Entities ({entities.length})
            </button>
            <button
              onClick={() => setActiveTab('alerts')}
              className={`flex-1 py-3 px-0.5 text-center text-[8px] font-black uppercase tracking-wider border-b-2 transition-all cursor-pointer ${activeTab === 'alerts' ? 'border-emerald-500 text-emerald-600 bg-white' : 'border-transparent text-slate-400 hover:text-slate-700'}`}
            >
              Alerts ({alertSubscriptions.length})
            </button>
            <button
              onClick={() => setActiveTab('bugs')}
              className={`flex-1 py-3 px-0.5 text-center text-[8px] font-black uppercase tracking-wider border-b-2 transition-all cursor-pointer ${activeTab === 'bugs' ? 'border-rose-500 text-rose-600 bg-white' : 'border-transparent text-slate-400 hover:text-slate-700'}`}
            >
              Bugs ({bugReports.length})
            </button>
            <button
              onClick={() => setActiveTab('sources')}
              className={`flex-1 py-3 px-0.5 text-center text-[8px] font-black uppercase tracking-wider border-b-2 transition-all cursor-pointer ${activeTab === 'sources' ? 'border-amber-500 text-amber-600 bg-white' : 'border-transparent text-slate-400 hover:text-slate-700'}`}
            >
              Sources ({sources.length})
            </button>
          </div>
          
          {/* Search/Filter bar for Entities */}
          {activeTab === 'entities' && (
            <div className="p-2 border-b border-slate-200 bg-slate-50/50 space-y-2 shrink-0">
              <div className="flex gap-2">
                <input 
                  type="text" 
                  placeholder="Search entities..." 
                  className="flex-1 px-3 py-1.5 border border-slate-200 bg-white text-xs outline-none rounded-lg focus:border-evergreen"
                  value={searchEntityQuery}
                  onChange={e => setSearchEntityQuery(e.target.value)}
                />
                <button
                  onClick={() => {
                    setSelectedEntityId(null);
                    setShowAddEntity(true);
                  }}
                  className="px-2.5 py-1.5 bg-gradient-to-br from-evergreen to-emerald-600 hover:from-emerald-700 hover:to-emerald-800 text-white rounded-lg text-xs font-bold transition-all flex items-center gap-1 cursor-pointer shrink-0 shadow-sm"
                  title="Register New Entity"
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="flex gap-1">
                {['all', 'city', 'school_district', 'port'].map(t => (
                  <button
                    key={t}
                    onClick={() => setFilterEntityType(t)}
                    className={`px-2 py-0.5 text-[8px] font-bold rounded capitalize border ${filterEntityType === t ? 'bg-evergreen text-white border-evergreen' : 'bg-white text-slate-500 border-slate-200'}`}
                  >
                    {t.replace('_', ' ')}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-3 custom-scrollbar space-y-2">
            {activeTab === 'correlations' ? (
              correlations.length === 0 ? (
                <div className="text-center py-20 px-4 text-slate-400 space-y-2">
                  <FileText className="w-8 h-8 text-slate-300 mx-auto" />
                  <h4 className="text-xs font-bold text-slate-600">Queue is Empty</h4>
                  <p className="text-[10px] text-slate-400 max-w-[180px] mx-auto leading-relaxed">
                    Generate new correlations or wait for the daily synchronization script.
                  </p>
                </div>
              ) : (
                correlations.map(c => (
                  <button
                    key={c.id}
                    onClick={() => selectCorrelation(c)}
                    className={`w-full text-left p-3.5 rounded-2xl border text-xs leading-relaxed transition-all flex flex-col gap-2 group relative overflow-hidden ${
                      c.id === selectedId 
                        ? 'bg-slate-100/80 border-slate-300/80 font-bold shadow-sm' 
                        : 'bg-transparent border-transparent hover:bg-slate-50 text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <div className={`absolute top-0 bottom-0 left-0 w-1 ${
                      c.status === 'approved' ? 'bg-emerald-500' : 'bg-amber-400'
                    }`} />
                    
                    <div className="flex justify-between items-start pl-1">
                      <span className="font-extrabold truncate pr-2 text-slate-900 group-hover:text-evergreen transition-colors">
                        {c.title}
                      </span>
                    </div>
                    <p className="text-[10px] text-slate-400 line-clamp-2 pl-1 leading-relaxed">
                      {c.hook}
                    </p>
                    
                    <div className="flex items-center justify-between pt-1 pl-1 shrink-0">
                      <span className={`text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded border ${
                        c.status === 'approved' 
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200' 
                          : 'bg-amber-50 text-amber-700 border-amber-200'
                      }`}>
                        {c.status}
                      </span>
                      <span className="text-[9px] text-slate-400 font-medium">
                        {new Date(c.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </button>
                ))
              )
            ) : activeTab === 'entities' ? (
              filteredEntities.length === 0 ? (
                <div className="text-center py-20 px-4 text-slate-400 space-y-2">
                  <Globe className="w-8 h-8 text-slate-300 mx-auto" />
                  <h4 className="text-xs font-bold text-slate-600">No Entities Found</h4>
                </div>
              ) : (
                filteredEntities.map(ent => (
                  <button
                    key={ent.id}
                    onClick={() => selectEntity(ent)}
                    className={`w-full text-left p-3.5 rounded-2xl border text-xs leading-relaxed transition-all flex flex-col gap-2 group relative overflow-hidden ${
                      ent.id === selectedEntityId 
                        ? 'bg-slate-100/80 border-slate-300/80 font-bold shadow-sm' 
                        : 'bg-transparent border-transparent hover:bg-slate-50 text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <div className={`absolute top-0 bottom-0 left-0 w-1 ${
                      ent.verification_status === 'verified' ? 'bg-blue-500' : 'bg-slate-300'
                    }`} />
                    
                    <div className="flex justify-between items-start pl-1">
                      <span className="font-extrabold truncate pr-2 text-slate-900 group-hover:text-evergreen transition-colors">
                        {ent.name}
                      </span>
                    </div>
                    
                    <div className="flex items-center justify-between pt-1 pl-1 shrink-0">
                      <span className={`text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded border ${
                        ent.verification_status === 'verified' 
                          ? 'bg-blue-50 text-blue-700 border-blue-200' 
                          : 'bg-slate-50 text-slate-700 border-slate-200'
                      }`}>
                        {ent.entity_type.replace('_', ' ')}
                      </span>
                      <span className="text-[9px] text-slate-400 font-medium">
                        {ent.platform || 'Generic'}
                      </span>
                    </div>
                  </button>
                ))
              )
            ) : activeTab === 'alerts' ? (
              alertSubscriptions.length === 0 ? (
                <div className="text-center py-20 px-4 text-slate-400 space-y-2">
                  <Megaphone className="w-8 h-8 text-slate-300 mx-auto" />
                  <h4 className="text-xs font-bold text-slate-600">No Alerts</h4>
                </div>
              ) : (
                alertSubscriptions.map(a => (
                  <button
                    key={a.id}
                    onClick={() => setSelectedAlertId(a.id)}
                    className={`w-full text-left p-3.5 rounded-2xl border text-xs leading-relaxed transition-all flex flex-col gap-2 group relative overflow-hidden ${
                      a.id === selectedAlertId 
                        ? 'bg-slate-100/80 border-slate-300/80 font-bold shadow-sm' 
                        : 'bg-transparent border-transparent hover:bg-slate-50 text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <div className="absolute top-0 bottom-0 left-0 w-1 bg-emerald-500" />
                    <div className="flex justify-between items-start pl-1">
                      <span className="font-extrabold truncate pr-2 text-slate-900 group-hover:text-evergreen transition-colors flex items-center gap-1.5">
                        <Megaphone className="w-3.5 h-3.5 text-emerald-500" />
                        <span>Alert #{a.id}</span>
                      </span>
                    </div>
                    <p className="text-[10px] text-slate-400 line-clamp-2 pl-1 leading-relaxed">
                      {a.topics}
                    </p>
                    <div className="flex items-center justify-between pt-1 pl-1 shrink-0">
                      <span className="text-[9px] text-slate-550 font-semibold">
                        {a.name || 'Anonymous'}
                      </span>
                      <span className="text-[9px] text-slate-400 font-medium">
                        {new Date(a.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </button>
                ))
              )
            ) : activeTab === 'bugs' ? (
              bugReports.length === 0 ? (
                <div className="text-center py-20 px-4 text-slate-400 space-y-2">
                  <Bug className="w-8 h-8 text-slate-300 mx-auto" />
                  <h4 className="text-xs font-bold text-slate-600">No Reports</h4>
                </div>
              ) : (
                bugReports.map(b => (
                  <button
                    key={b.id}
                    onClick={() => setSelectedBugId(b.id)}
                    className={`w-full text-left p-3.5 rounded-2xl border text-xs leading-relaxed transition-all flex flex-col gap-2 group relative overflow-hidden ${
                      b.id === selectedBugId 
                        ? 'bg-slate-100/80 border-slate-300/80 font-bold shadow-sm' 
                        : 'bg-transparent border-transparent hover:bg-slate-50 text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <div className={`absolute top-0 bottom-0 left-0 w-1 ${
                      b.report_type === 'bug' ? 'bg-rose-500' : 'bg-emerald-500'
                    }`} />
                    <div className="flex justify-between items-start pl-1">
                      <span className="font-extrabold truncate pr-2 text-slate-900 group-hover:text-evergreen transition-colors flex items-center gap-1.5">
                        {b.report_type === 'bug' ? <Bug className="w-3.5 h-3.5 text-rose-500" /> : <Megaphone className="w-3.5 h-3.5 text-emerald-500" />}
                        <span>{b.report_type === 'bug' ? 'Bug Report' : 'Civic Tip'} #{b.id}</span>
                      </span>
                    </div>
                    <p className="text-[10px] text-slate-400 line-clamp-2 pl-1 leading-relaxed">
                      {b.description}
                    </p>
                    <div className="flex items-center justify-between pt-1 pl-1 shrink-0">
                      <span className="text-[9px] text-slate-500 font-semibold">
                        {b.name || 'Anonymous'}
                      </span>
                      <span className="text-[9px] text-slate-400 font-medium">
                        {new Date(b.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </button>
                ))
              )
            ) : (
              sources.length === 0 ? (
                <div className="text-center py-20 px-4 text-slate-400 space-y-2">
                  <Database className="w-8 h-8 text-slate-300 mx-auto animate-pulse" />
                  <h4 className="text-xs font-bold text-slate-600">No Sources Found</h4>
                </div>
              ) : (
                sources.map(src => (
                  <button
                    key={src.id}
                    onClick={() => setSelectedSourceId(src.id)}
                    className={`w-full text-left p-3.5 rounded-2xl border text-xs leading-relaxed transition-all flex flex-col gap-2 group relative overflow-hidden ${
                      src.id === selectedSourceId 
                        ? 'bg-slate-100/80 border-slate-300/80 font-bold shadow-sm' 
                        : 'bg-transparent border-transparent hover:bg-slate-50 text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    <div className="absolute top-0 bottom-0 left-0 w-1 bg-amber-500" />
                    <div className="flex justify-between items-start pl-1">
                      <span className="font-extrabold truncate pr-2 text-slate-900 group-hover:text-evergreen transition-colors flex items-center gap-1.5">
                        <Database className="w-3.5 h-3.5 text-amber-500" />
                        <span>{src.name}</span>
                      </span>
                    </div>
                    <div className="flex items-center justify-between pt-1 pl-1 shrink-0">
                      <span className="text-[9px] font-black text-amber-700 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded">
                        {src.count.toLocaleString()} rows
                      </span>
                      <span className="text-[8px] text-slate-400 font-medium truncate max-w-[120px]">
                        {src.db_source}
                      </span>
                    </div>
                  </button>
                ))
              )
            )}
          </div>
        </aside>

        {/* Right Column: Interactive Editor and Details */}
        <main className="flex-1 overflow-y-auto p-8 custom-scrollbar bg-slate-50/40">
          {activeTab === 'correlations' ? (
            activeCorr ? (
              <div className="max-w-3xl mx-auto space-y-6">
                
                {/* Toolbar Actions Card */}
                <div className="p-4 rounded-3xl bg-white border border-slate-200/80 flex items-center justify-between shadow-sm relative overflow-hidden shrink-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-[9px] font-black tracking-widest uppercase px-2 py-0.5 rounded border ${
                      activeCorr.status === 'approved' 
                        ? 'bg-emerald-50 text-emerald-700 border-emerald-200' 
                        : 'bg-amber-50 text-amber-700 border-amber-200'
                    }`}>
                      {activeCorr.status} draft
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    {isEditing ? (
                      <>
                        <button 
                          onClick={() => handleSaveChanges(activeCorr.id)}
                          disabled={actionLoading !== null}
                          className="flex items-center gap-1.5 px-3.5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold transition-all shadow-sm cursor-pointer disabled:opacity-50"
                        >
                          <Save className="w-3.5 h-3.5" />
                          <span>Save Changes</span>
                        </button>
                        <button 
                          onClick={() => setIsEditing(false)}
                          className="px-3.5 py-2 border border-slate-200 hover:bg-slate-50 text-slate-500 rounded-xl text-xs font-bold transition-colors cursor-pointer"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button 
                          onClick={() => setIsEditing(true)}
                          className="flex items-center gap-1.5 px-3.5 py-2 border border-slate-200 hover:bg-slate-50 text-slate-666 rounded-xl text-xs font-bold transition-colors cursor-pointer"
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                          <span>Edit Content</span>
                        </button>
                        
                        {activeCorr.status !== 'approved' && (
                          <button 
                            onClick={() => handleApprove(activeCorr.id)}
                            disabled={actionLoading !== null}
                            className="flex items-center gap-1.5 px-3.5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold transition-all shadow-sm cursor-pointer disabled:opacity-50 shadow-emerald-600/10"
                          >
                            <Check className="w-3.5 h-3.5" />
                            <span>Approve & Publish</span>
                          </button>
                        )}
                        
                        <button 
                          onClick={() => handleDismiss(activeCorr.id)}
                          disabled={actionLoading !== null}
                          className="flex items-center gap-1.5 px-3.5 py-2 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-150 rounded-xl text-xs font-bold transition-colors cursor-pointer disabled:opacity-50"
                        >
                          <X className="w-3.5 h-3.5" />
                          <span>Dismiss</span>
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Editor Workspace */}
                <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 space-y-6 shadow-sm">
                  {isEditing ? (
                    <div className="space-y-4">
                      <div>
                        <label className="block text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1.5 pl-0.5">Headline Title</label>
                        <input 
                          type="text"
                          className="w-full px-4.5 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all"
                          value={editTitle}
                          onChange={e => setEditTitle(e.target.value)}
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1.5 pl-0.5">Teaser Hook</label>
                        <textarea 
                          rows={2}
                          className="w-full px-4.5 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-sm font-semibold transition-all resize-none"
                          value={editHook}
                          onChange={e => setEditHook(e.target.value)}
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1.5 pl-0.5">Report Report Markdown</label>
                        <textarea 
                          rows={12}
                          className="w-full px-4.5 py-3 border border-slate-200 bg-slate-50 text-slate-900 outline-none rounded-xl focus:border-evergreen focus:bg-white text-xs font-mono transition-all"
                          value={editMarkdown}
                          onChange={e => setEditMarkdown(e.target.value)}
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-6">
                      <div>
                        <h2 className="text-xl md:text-2xl font-black text-slate-900 tracking-tight leading-tight">
                          {activeCorr.title}
                        </h2>
                        <p className="text-xs md:text-sm text-slate-500 font-medium mt-3 leading-relaxed border-l-2 border-emerald-500/60 pl-3.5 italic bg-slate-50/50 py-1 rounded-r-lg">
                          "{activeCorr.hook}"
                        </p>
                      </div>
                      
                      <div className="prose prose-sm prose-slate max-w-none pt-4 border-t border-slate-100 text-xs md:text-sm leading-relaxed text-slate-700 font-medium space-y-4 whitespace-pre-wrap">
                        {activeCorr.report_markdown}
                      </div>
                    </div>
                  )}
                </div>

                {/* Citations Reference Drawer */}
                <div className="bg-white border border-slate-200/80 rounded-3xl p-6 shadow-sm space-y-4">
                  <h3 className="text-xs font-black text-slate-500 uppercase tracking-wider pl-0.5">
                    Identified Citations & Verbatim Context Audit ({activeCorr.citations.length})
                  </h3>
                  
                  <div className="space-y-4.5">
                    {activeCorr.citations.map((cit, cIdx) => (
                      <div 
                        key={cIdx}
                        className="p-5 rounded-2xl bg-slate-50/70 border border-slate-200/60 hover:bg-slate-50 transition-colors group space-y-3"
                      >
                        <div className="flex items-start justify-between">
                          <div className="min-w-0 pr-2">
                            <span className={`text-[7px] font-black uppercase px-1.5 py-0.2 rounded border ${
                              cit.source === 'audit' 
                                ? 'bg-purple-50 text-purple-700 border-purple-200' 
                                : 'bg-blue-50 text-blue-700 border-blue-200'
                            }`}>
                              {cit.source === 'audit' ? 'Audit ID: ' + cit.id : 'Council Action: ' + cit.id}
                            </span>
                            <span className="text-[7px] font-black uppercase px-1.5 py-0.2 rounded border bg-slate-100 text-slate-600 border-slate-200 ml-1.5">
                              {cit.meeting_type || 'Unknown'}
                            </span>
                            <span className="text-[7px] font-black uppercase px-1.5 py-0.2 rounded border bg-emerald-50 text-emerald-700 border-emerald-250 ml-1.5">
                              Score: {cit.verification_score !== undefined ? (cit.verification_score * 100).toFixed(0) + '%' : '100%'}
                            </span>
                            <h4 className="text-[11px] font-extrabold text-slate-800 truncate mt-1">
                              {cit.title}
                            </h4>
                          </div>
                          
                          {cit.url && (
                            <a 
                              href={cit.url} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="w-7 h-7 rounded-lg border border-slate-200 bg-white flex items-center justify-center shrink-0 text-slate-400 group-hover:text-evergreen group-hover:border-evergreen/30 transition-colors cursor-pointer"
                            >
                              <ExternalLink className="w-3.5 h-3.5" />
                            </a>
                          )}
                        </div>

                        {/* Verbatim Context Snippet Box */}
                        <div className="p-3 bg-amber-50/30 border border-amber-100 rounded-xl space-y-1">
                          <span className="block text-[8px] font-black text-amber-600 uppercase tracking-widest pl-0.5">Verbatim Audit Trail context:</span>
                          <p className="text-[10px] text-slate-650 leading-relaxed font-semibold italic">
                            "{cit.verbatim_text_context || 'No verbatim context captured during sync.'}"
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

              </div>
            ) : (
              <div className="flex flex-col items-center justify-center text-center py-36 px-4 text-slate-400 space-y-3">
                <FileText className="w-12 h-12 text-slate-300" />
                <div>
                  <h4 className="text-xs font-bold text-slate-600">Select a Correlation</h4>
                  <p className="text-[10px] text-slate-400 mt-1 max-w-[200px] leading-relaxed mx-auto">
                    Click a correlation item from the list on the left to review, edit, or approve.
                  </p>
                </div>
              </div>
            )
          ) : activeTab === 'entities' ? (
            activeEntity ? (
              <div className="max-w-3xl mx-auto space-y-6">
                
                {/* Entity Detail Header Card */}
                <div className="p-6 bg-white border border-slate-200/80 rounded-3xl shadow-sm space-y-4">
                  <div className="flex justify-between items-start">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-100 flex items-center justify-center text-blue-600">
                        <Globe className="w-5 h-5" />
                      </div>
                      <div>
                        <h2 className="font-extrabold text-base text-slate-900 tracking-tight">{activeEntity.name}</h2>
                        <span className="text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded border bg-blue-50 text-blue-700 border-blue-200">
                          {activeEntity.entity_type.replace('_', ' ')}
                        </span>
                        <span className={`text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded border ml-1.5 ${activeEntity.verification_status === 'verified' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-500 border-slate-200'}`}>
                          {activeEntity.verification_status}
                        </span>
                      </div>
                    </div>

                    <div className="flex gap-2">
                      {activeEntity.verification_status !== 'verified' && (
                        <button
                          onClick={() => handleVerifyEntity(activeEntity.id)}
                          className="px-3 py-1.5 bg-emerald-650 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold transition-all shadow-sm cursor-pointer"
                        >
                          Verify URL
                        </button>
                      )}
                      <button
                        onClick={() => setIsEditingEntity(!isEditingEntity)}
                        className="px-3 py-1.5 border border-slate-200 hover:bg-slate-100 text-slate-600 rounded-lg text-xs font-bold transition-all cursor-pointer"
                      >
                        {isEditingEntity ? 'Cancel' : 'Edit Settings'}
                      </button>
                    </div>
                  </div>

                  {isEditingEntity ? (
                    <div className="p-4 bg-slate-50 border border-slate-200/60 rounded-2xl space-y-4">
                      <div className="border-b border-slate-200 pb-2">
                        <h4 className="text-xs font-black text-slate-600 uppercase tracking-wider">Basic Metadata</h4>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Official Website URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityUrl}
                            onChange={e => setEditEntityUrl(e.target.value)}
                          />
                        </div>
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Agenda Portal Scraping URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityPortal}
                            onChange={e => setEditEntityPortal(e.target.value)}
                            placeholder="e.g. https://webapi.legistar.com/v1/city/events"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Scraping Adapter Driver</label>
                          <select 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityPlatform}
                            onChange={e => setEditEntityPlatform(e.target.value)}
                          >
                            <option value="Legistar">Legistar API</option>
                            <option value="Granicus">Granicus</option>
                            <option value="CivicWeb">CivicWeb</option>
                            <option value="CivicPlus/CivicWeb">CivicPlus (AgendaCenter)</option>
                            <option value="MuniCode">MuniCode</option>
                            <option value="Generic Crawler">Generic PDF Crawler</option>
                            <option value="Unreachable">Unreachable / Manual Upload</option>
                          </select>
                        </div>
                        <div className="flex items-center gap-2 pl-0.5 pt-4">
                          <input 
                            type="checkbox" 
                            id="edit-entity-active" 
                            checked={editEntityActive}
                            onChange={e => setEditEntityActive(e.target.checked)}
                          />
                          <label htmlFor="edit-entity-active" className="text-xs font-bold text-slate-600">Active Monitoring Enabled</label>
                        </div>
                      </div>

                      <div className="border-b border-slate-200 pt-2 pb-2">
                        <h4 className="text-xs font-black text-slate-600 uppercase tracking-wider">Sources & Ingestion Locations</h4>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Minutes Location URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityMinutesUrl}
                            onChange={e => setEditEntityMinutesUrl(e.target.value)}
                            placeholder="e.g. https://city.gov/minutes"
                          />
                        </div>
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Agenda Location URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityAgendaUrl}
                            onChange={e => setEditEntityAgendaUrl(e.target.value)}
                            placeholder="e.g. https://city.gov/agendas"
                          />
                        </div>
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Agenda Packets URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityPacketsUrl}
                            onChange={e => setEditEntityPacketsUrl(e.target.value)}
                            placeholder="e.g. https://city.gov/packets"
                          />
                        </div>
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Video Streams Digest URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityVideoUrl}
                            onChange={e => setEditEntityVideoUrl(e.target.value)}
                            placeholder="e.g. https://youtube.com/@city"
                          />
                        </div>
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Audio Streams Digest URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityAudioUrl}
                            onChange={e => setEditEntityAudioUrl(e.target.value)}
                            placeholder="e.g. https://soundcloud.com/city"
                          />
                        </div>
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Meeting Transcripts URL</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityTranscriptsUrl}
                            onChange={e => setEditEntityTranscriptsUrl(e.target.value)}
                            placeholder="e.g. https://city.gov/transcripts"
                          />
                        </div>
                      </div>

                      <div className="border-b border-slate-200 pt-2 pb-2">
                        <h4 className="text-xs font-black text-slate-600 uppercase tracking-wider">Scraper Crawler Directives</h4>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Path Filter Regex</label>
                          <input 
                            type="text" 
                            className="w-full px-3.5 py-2 border border-slate-200 bg-white text-xs rounded-lg focus:border-evergreen outline-none"
                            value={editEntityCrawlPathFilter}
                            onChange={e => setEditEntityCrawlPathFilter(e.target.value)}
                            placeholder="e.g. *minutes*, *.pdf"
                          />
                        </div>
                        <div className="space-y-1">
                          <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Crawl Document Types</label>
                          <div className="flex gap-4 pt-1">
                            {['Minutes', 'Agendas'].map(t => (
                              <label key={t} className="inline-flex items-center gap-1.5 text-xs text-slate-650 font-semibold">
                                <input 
                                  type="checkbox" 
                                  checked={editEntityCrawlDocTypes.includes(t)}
                                  onChange={e => {
                                    if (e.target.checked) setEditEntityCrawlDocTypes(prev => [...prev, t]);
                                    else setEditEntityCrawlDocTypes(prev => prev.filter(x => x !== t));
                                  }}
                                />
                                <span>{t}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                      </div>

                      <div className="pt-2 flex gap-2">
                        <button
                          onClick={() => handleEditEntity(activeEntity.id)}
                          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-bold transition-all cursor-pointer"
                        >
                          Save Settings
                        </button>
                        <button
                          onClick={() => setIsEditingEntity(false)}
                          className="px-4 py-2 border border-slate-200 hover:bg-slate-100 text-slate-500 rounded-lg text-xs font-bold transition-all cursor-pointer"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-4 text-xs">
                      <div className="p-3 bg-slate-50 rounded-xl border">
                        <span className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-0.5">Website URL</span>
                        <a href={activeEntity.official_url} target="_blank" rel="noopener noreferrer" className="text-evergreen font-semibold hover:underline truncate block">
                          {activeEntity.official_url}
                        </a>
                      </div>
                      <div className="p-3 bg-slate-50 rounded-xl border">
                        <span className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-0.5">Platform Adapter</span>
                        <span className="font-semibold text-slate-800">{activeEntity.platform || 'None / Custom Crawler'}</span>
                      </div>
                      <div className="p-3 bg-slate-50 rounded-xl border col-span-2">
                        <span className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-0.5">Agenda Portal URL</span>
                        <span className="font-semibold text-slate-600 truncate block">{activeEntity.agenda_portal_url || 'Not Registered'}</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Jurisdiction Sources Grid */}
                <div className="p-6 bg-white border border-slate-200/80 rounded-3xl shadow-sm space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Database className="w-4 h-4 text-slate-500" />
                      <h3 className="text-xs font-black text-slate-500 uppercase tracking-wider pl-0.5">Jurisdiction Sources & Ingestion</h3>
                    </div>
                    {/* Compact Trigger Crawl action next to sources if platform adapter is a crawler */}
                    {activeEntity.platform && activeEntity.platform !== 'Unreachable' && activeEntity.platform !== 'None' && (
                      <button
                        onClick={handleTriggerCrawl}
                        disabled={actionLoading === 'triggering_crawl'}
                        className="inline-flex items-center gap-1.5 px-3 py-1 bg-gradient-to-br from-evergreen to-emerald-600 hover:from-emerald-700 hover:to-emerald-800 text-white rounded-lg text-[10px] font-bold transition-all shadow-sm cursor-pointer disabled:opacity-50"
                      >
                        {actionLoading === 'triggering_crawl' ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3 fill-current" />}
                        <span>Trigger Ingestion Sync</span>
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Website */}
                    <div className="p-4 bg-slate-50/50 hover:bg-slate-50 border border-slate-250/50 rounded-2xl transition-all flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center shrink-0">
                          <Globe className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="block text-[8px] font-black text-slate-400 uppercase tracking-wider mb-0.5">Official Website</span>
                          <span className="text-xs font-extrabold text-slate-800 block truncate">
                            {activeEntity.official_url || 'Not Configured'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.official_url && (
                        <a href={activeEntity.official_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 group-hover:text-blue-600 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Agenda Portal */}
                    <div className="p-4 bg-slate-50/50 hover:bg-slate-50 border border-slate-250/50 rounded-2xl transition-all flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
                          <Link2 className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="block text-[8px] font-black text-slate-400 uppercase tracking-wider mb-0.5">Agenda Portal</span>
                          <span className={`text-xs font-extrabold block truncate ${activeEntity.agenda_portal_url ? 'text-slate-800' : 'text-slate-400 italic font-semibold'}`}>
                            {activeEntity.agenda_portal_url || 'No Agenda Portal configured'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.agenda_portal_url && (
                        <a href={activeEntity.agenda_portal_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 group-hover:text-emerald-600 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Minutes URL */}
                    <div className="p-4 bg-slate-50/50 hover:bg-slate-50 border border-slate-250/50 rounded-2xl transition-all flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center shrink-0">
                          <FileText className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="block text-[8px] font-black text-slate-400 uppercase tracking-wider mb-0.5">Meeting Minutes Source</span>
                          <span className={`text-xs font-extrabold block truncate ${activeEntity.minutes_url ? 'text-slate-800' : 'text-slate-400 italic font-semibold'}`}>
                            {activeEntity.minutes_url || 'No Minutes Location registered'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.minutes_url && (
                        <a href={activeEntity.minutes_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 group-hover:text-purple-600 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Agenda URL */}
                    <div className="p-4 bg-slate-50/50 hover:bg-slate-50 border border-slate-250/50 rounded-2xl transition-all flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                          <FileText className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="block text-[8px] font-black text-slate-400 uppercase tracking-wider mb-0.5">Meeting Agendas Source</span>
                          <span className={`text-xs font-extrabold block truncate ${activeEntity.agenda_url ? 'text-slate-800' : 'text-slate-400 italic font-semibold'}`}>
                            {activeEntity.agenda_url || 'No Agenda Location registered'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.agenda_url && (
                        <a href={activeEntity.agenda_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 group-hover:text-indigo-600 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Packets URL */}
                    <div className="p-4 bg-slate-50/50 border border-slate-250/50 rounded-2xl flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-slate-100 text-slate-500 flex items-center justify-center shrink-0">
                          <FileText className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[8px] font-black text-slate-400 uppercase tracking-wider">Agenda Packets</span>
                            <span className="text-[7px] font-bold px-1 py-0.2 bg-slate-150 text-slate-500 border border-slate-200 rounded">Not Ingested</span>
                          </div>
                          <span className={`text-xs font-extrabold block truncate ${activeEntity.packets_url ? 'text-slate-800' : 'text-slate-400 italic font-semibold'}`}>
                            {activeEntity.packets_url || 'No Packets Location registered'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.packets_url && (
                        <a href={activeEntity.packets_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-slate-650 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Video Stream URL */}
                    <div className="p-4 bg-slate-50/50 hover:bg-slate-50 border border-slate-250/50 rounded-2xl transition-all flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-rose-50 text-rose-600 flex items-center justify-center shrink-0">
                          <Video className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="block text-[8px] font-black text-slate-400 uppercase tracking-wider mb-0.5">Video stream digests</span>
                          <span className={`text-xs font-extrabold block truncate ${activeEntity.video_url ? 'text-slate-800' : 'text-slate-400 italic font-semibold'}`}>
                            {activeEntity.video_url || 'No Video Digests URL registered'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.video_url && (
                        <a href={activeEntity.video_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 group-hover:text-rose-600 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Audio Streams URL */}
                    <div className="p-4 bg-slate-50/50 hover:bg-slate-50 border border-slate-250/50 rounded-2xl transition-all flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-orange-50 text-orange-600 flex items-center justify-center shrink-0">
                          <Volume2 className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <span className="block text-[8px] font-black text-slate-400 uppercase tracking-wider mb-0.5">Audio streams digests</span>
                          <span className={`text-xs font-extrabold block truncate ${activeEntity.audio_url ? 'text-slate-800' : 'text-slate-400 italic font-semibold'}`}>
                            {activeEntity.audio_url || 'No Audio Digests URL registered'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.audio_url && (
                        <a href={activeEntity.audio_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 group-hover:text-orange-600 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                    {/* Transcripts URL */}
                    <div className="p-4 bg-slate-50/50 border border-slate-250/50 rounded-2xl flex items-start justify-between group">
                      <div className="flex items-start gap-3 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-teal-50 text-teal-600 flex items-center justify-center shrink-0">
                          <MessageSquare className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[8px] font-black text-slate-400 uppercase tracking-wider">Meeting Transcripts</span>
                            <span className="text-[7px] font-bold px-1 py-0.2 bg-teal-100 text-teal-600 border border-teal-200 rounded">Future Support</span>
                          </div>
                          <span className={`text-xs font-extrabold block truncate ${activeEntity.transcripts_url ? 'text-slate-800' : 'text-slate-400 italic font-semibold'}`}>
                            {activeEntity.transcripts_url || 'No Transcripts URL registered'}
                          </span>
                        </div>
                      </div>
                      {activeEntity.transcripts_url && (
                        <a href={activeEntity.transcripts_url} target="_blank" rel="noopener noreferrer" className="text-slate-400 hover:text-teal-600 transition-colors pt-1">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>

                  </div>
                </div>

              </div>
            ) : showAddEntity ? (
              <div className="max-w-3xl mx-auto space-y-6">
                <div className="p-6 bg-white border border-slate-200/80 rounded-3xl shadow-sm space-y-4">
                  <div className="flex justify-between items-center pb-2 border-b border-slate-100">
                    <div>
                      <h2 className="font-extrabold text-base text-slate-900 tracking-tight">Register New Jurisdiction / Entity</h2>
                      <p className="text-[10px] text-slate-400 font-medium">Add a city, school district, port, or county to the authoritative catalog.</p>
                    </div>
                    <button
                      onClick={() => setShowAddEntity(false)}
                      className="px-3 py-1.5 border border-slate-200 hover:bg-slate-100 text-slate-500 rounded-lg text-xs font-bold transition-all cursor-pointer"
                    >
                      Cancel
                    </button>
                  </div>

                  <form onSubmit={handleAddEntity} className="space-y-4 text-xs">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Entity Name</label>
                        <input 
                          type="text" 
                          required
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityName}
                          onChange={e => setNewEntityName(e.target.value)}
                          placeholder="e.g. Port of Edmonds"
                        />
                      </div>
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Entity Type</label>
                        <select 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityType}
                          onChange={e => setNewEntityType(e.target.value)}
                        >
                          <option value="school_district">School District</option>
                          <option value="port">Port District</option>
                          <option value="city">City / Town</option>
                          <option value="county">County</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Official Website URL</label>
                        <input 
                          type="url" 
                          required
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityUrl}
                          onChange={e => setNewEntityUrl(e.target.value)}
                          placeholder="e.g. https://www.portofedmonds.org/"
                        />
                      </div>
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Agenda Portal URL (Optional)</label>
                        <input 
                          type="url" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityPortal}
                          onChange={e => setNewEntityPortal(e.target.value)}
                          placeholder="e.g. https://city-edmonds.civicweb.net/portal/"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Scraping Platform</label>
                        <select 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityPlatform}
                          onChange={e => setNewEntityPlatform(e.target.value)}
                        >
                          <option value="Generic Crawler">Generic Crawler</option>
                          <option value="Legistar">Legistar API</option>
                          <option value="Granicus">Granicus</option>
                          <option value="CivicWeb">CivicWeb</option>
                          <option value="CivicPlus/CivicWeb">CivicPlus (AgendaCenter)</option>
                          <option value="Unreachable">Unreachable / Manual Upload</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Minutes Location URL</label>
                        <input 
                          type="url" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityMinutesUrl}
                          onChange={e => setNewEntityMinutesUrl(e.target.value)}
                          placeholder="e.g. https://www.portofedmonds.org/minutes"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Agenda Location URL</label>
                        <input 
                          type="url" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityAgendaUrl}
                          onChange={e => setNewEntityAgendaUrl(e.target.value)}
                          placeholder="e.g. https://www.portofedmonds.org/agendas"
                        />
                      </div>
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Agenda Packets URL</label>
                        <input 
                          type="url" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityPacketsUrl}
                          onChange={e => setNewEntityPacketsUrl(e.target.value)}
                          placeholder="e.g. https://www.portofedmonds.org/packets"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Video stream digests URL</label>
                        <input 
                          type="url" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityVideoUrl}
                          onChange={e => setNewEntityVideoUrl(e.target.value)}
                          placeholder="e.g. https://youtube.com/@port"
                        />
                      </div>
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Audio streams digests URL</label>
                        <input 
                          type="url" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityAudioUrl}
                          onChange={e => setNewEntityAudioUrl(e.target.value)}
                          placeholder="e.g. https://soundcloud.com/port"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Meeting transcripts URL</label>
                        <input 
                          type="url" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityTranscriptsUrl}
                          onChange={e => setNewEntityTranscriptsUrl(e.target.value)}
                          placeholder="e.g. https://www.portofedmonds.org/transcripts"
                        />
                      </div>
                      <div>
                        <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Path Filter Regex</label>
                        <input 
                          type="text" 
                          className="w-full px-3.5 py-2 border border-slate-200 rounded-lg outline-none bg-slate-50 focus:bg-white focus:border-evergreen"
                          value={newEntityCrawlPathFilter}
                          onChange={e => setNewEntityCrawlPathFilter(e.target.value)}
                          placeholder="e.g. *minutes*, *.pdf"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1 pl-0.5">Crawl Document Types</label>
                      <div className="flex gap-4 pt-1">
                        {['Minutes', 'Agendas'].map(t => (
                          <label key={t} className="inline-flex items-center gap-1.5 text-xs text-slate-650 font-semibold">
                            <input 
                              type="checkbox" 
                              checked={newEntityCrawlDocTypes.includes(t)}
                              onChange={e => {
                                if (e.target.checked) setNewEntityCrawlDocTypes(prev => [...prev, t]);
                                else setNewEntityCrawlDocTypes(prev => prev.filter(x => x !== t));
                              }}
                            />
                            <span>{t}</span>
                          </label>
                        ))}
                      </div>
                    </div>

                    <button
                      type="submit"
                      disabled={actionLoading === 'adding_entity'}
                      className="px-5 py-2.5 bg-gradient-to-br from-evergreen to-emerald-600 hover:from-emerald-700 hover:to-emerald-800 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-evergreen/10 cursor-pointer disabled:opacity-50 flex items-center justify-center gap-2"
                    >
                      {actionLoading === 'adding_entity' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                      <span>Register Entity & Directory</span>
                    </button>
                  </form>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center text-center py-36 px-4 text-slate-400 space-y-3">
                <Globe className="w-12 h-12 text-slate-300" />
                <div>
                  <h4 className="text-xs font-bold text-slate-600">Select an Entity</h4>
                  <p className="text-[10px] text-slate-400 mt-1 max-w-[200px] leading-relaxed mx-auto">
                    Click an entity from the list on the left to review, verify official websites, or set crawling parameters. Or click the <strong>+</strong> button in the left sidebar to register a new entity.
                  </p>
                </div>
              </div>
            )
          ) : activeTab === 'alerts' ? (
            activeAlert ? (
              <div className="max-w-3xl mx-auto space-y-6">
                
                {/* Toolbar Actions Card */}
                <div className="p-4 rounded-3xl bg-white border border-slate-200/80 flex items-center justify-between shadow-sm relative overflow-hidden shrink-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] font-black tracking-widest uppercase px-2 py-0.5 rounded border bg-emerald-50 text-emerald-700 border-emerald-200">
                      Civic Alert Subscription
                    </span>
                    <span className="text-xs text-slate-400 font-medium pl-1">
                      Registered on {new Date(activeAlert.created_at).toLocaleString()}
                    </span>
                  </div>

                  <button 
                    onClick={() => handleDeleteAlert(activeAlert.id)}
                    disabled={actionLoading !== null}
                    className="flex items-center gap-1.5 px-3.5 py-2 bg-rose-650 hover:bg-rose-700 text-white rounded-xl text-xs font-bold transition-all shadow-sm cursor-pointer disabled:opacity-50"
                  >
                    <X className="w-3.5 h-3.5" />
                    <span>Delete & Unsubscribe</span>
                  </button>
                </div>

                {/* Alert Details Card */}
                <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 space-y-6 shadow-sm">
                  <div className="flex items-center gap-3.5">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center shadow-sm border bg-emerald-50 border-emerald-100 text-emerald-600">
                      <Megaphone className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="text-sm md:text-base font-extrabold text-slate-900 leading-snug">
                        Alert Subscription #{activeAlert.id}
                      </h3>
                      <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-0.5">
                        Subscriber & Topic Profile
                      </p>
                    </div>
                  </div>

                  <div className="border border-slate-100 rounded-2xl overflow-hidden bg-slate-50/50 text-xs">
                    <table className="min-w-full divide-y divide-slate-100">
                      <tbody>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider w-1/3 border-r border-slate-100">Subscriber Name</td>
                          <td className="px-4 py-3 font-semibold text-slate-800">{activeAlert.name}</td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Subscriber Email</td>
                          <td className="px-4 py-3 font-semibold text-slate-800">
                            <a href={`mailto:${activeAlert.email}`} className="text-evergreen hover:underline">
                              {activeAlert.email}
                            </a>
                          </td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Jurisdiction Target</td>
                          <td className="px-4 py-3 font-semibold text-slate-800">{activeAlert.jurisdiction || 'All Washington'}</td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Anonymous User ID</td>
                          <td className="px-4 py-3 font-mono text-[10px] text-slate-500 select-all">{activeAlert.anonymous_user_id || 'unknown'}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <div className="pt-5 border-t border-slate-100 space-y-4">
                    <div>
                      <label className="block text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2 pl-0.5">
                        Topics of Interest
                      </label>
                      <div className="p-5 bg-slate-50 border border-slate-200/60 rounded-2xl text-slate-700 leading-relaxed font-medium text-xs md:text-sm whitespace-pre-wrap">
                        {activeAlert.topics}
                      </div>
                    </div>

                    {activeAlert.query && (
                      <div>
                        <label className="block text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2 pl-0.5">
                          Specific Query / Search Filters
                        </label>
                        <div className="p-5 bg-slate-50 border border-slate-200/60 rounded-2xl text-slate-650 leading-relaxed font-medium text-xs md:text-sm whitespace-pre-wrap">
                          {activeAlert.query}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center text-center py-36 px-4 text-slate-400 space-y-3">
                <Megaphone className="w-12 h-12 text-slate-300" />
                <div>
                  <h4 className="text-xs font-bold text-slate-600">Select an Alert</h4>
                  <p className="text-[10px] text-slate-400 mt-1 max-w-[200px] leading-relaxed mx-auto">
                    Click an alert subscription from the list on the left to review its details.
                  </p>
                </div>
              </div>
            )
          ) : activeTab === 'bugs' ? (
            activeBug ? (
              <div className="max-w-3xl mx-auto space-y-6">
                
                {/* Toolbar Actions Card */}
                <div className="p-4 rounded-3xl bg-white border border-slate-200/80 flex items-center justify-between shadow-sm relative overflow-hidden shrink-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-[9px] font-black tracking-widest uppercase px-2 py-0.5 rounded border ${
                      activeBug.report_type === 'bug' 
                        ? 'bg-rose-50 text-rose-700 border-rose-200' 
                        : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    }`}>
                      {activeBug.report_type === 'bug' ? 'Bug Report' : 'Civic Tip'}
                    </span>
                    <span className="text-xs text-slate-400 font-medium pl-1">
                      Submitted on {new Date(activeBug.created_at).toLocaleString()}
                    </span>
                  </div>

                  <button 
                    onClick={() => handleDeleteBug(activeBug.id)}
                    disabled={actionLoading !== null}
                    className="flex items-center gap-1.5 px-3.5 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-xl text-xs font-bold transition-all shadow-sm cursor-pointer disabled:opacity-50"
                  >
                    <Check className="w-3.5 h-3.5" />
                    <span>Resolve & Remove</span>
                  </button>
                </div>

                {/* Bug Details Card */}
                <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 space-y-6 shadow-sm">
                  <div className="flex items-center gap-3.5">
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center shadow-sm border ${
                      activeBug.report_type === 'bug' 
                        ? 'bg-rose-50 border-rose-100 text-rose-500' 
                        : 'bg-emerald-50 border-emerald-100 text-emerald-500'
                    }`}>
                      {activeBug.report_type === 'bug' ? <Bug className="w-5 h-5" /> : <Megaphone className="w-5 h-5" />}
                    </div>
                    <div>
                      <h3 className="text-sm md:text-base font-extrabold text-slate-900 leading-snug">
                        {activeBug.report_type === 'bug' ? 'Bug Report' : 'Civic Tip'} #{activeBug.id}
                      </h3>
                      <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-0.5">
                        Details & Submission Metadata
                      </p>
                    </div>
                  </div>

                  <div className="border border-slate-100 rounded-2xl overflow-hidden bg-slate-50/50 text-xs">
                    <table className="min-w-full divide-y divide-slate-100">
                      <tbody>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider w-1/3 border-r border-slate-100">Submitter Name</td>
                          <td className="px-4 py-3 font-semibold text-slate-800">{activeBug.name || 'Anonymous'}</td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Submitter Email</td>
                          <td className="px-4 py-3 font-semibold text-slate-800">
                            {activeBug.email ? (
                              <a href={`mailto:${activeBug.email}`} className="text-evergreen hover:underline">
                                {activeBug.email}
                              </a>
                            ) : (
                              'Not provided'
                            )}
                          </td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Anonymous User ID</td>
                          <td className="px-4 py-3 font-mono text-[10px] text-slate-500 select-all">{activeBug.anonymous_user_id || 'unknown'}</td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Session ID</td>
                          <td className="px-4 py-3 font-mono text-[10px] text-slate-500 select-all">{activeBug.session_id || 'unknown'}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <div className="pt-5 border-t border-slate-100">
                    <label className="block text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2 pl-0.5">
                      {activeBug.report_type === 'bug' ? 'Issue Description' : 'Tip Context & Body'}
                    </label>
                    <div className="p-5 bg-slate-50 border border-slate-200/60 rounded-2xl text-slate-700 leading-relaxed font-medium text-xs md:text-sm whitespace-pre-wrap">
                      {activeBug.description}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center text-center py-36 px-4 text-slate-400 space-y-3">
                <Bug className="w-12 h-12 text-slate-300" />
                <div>
                  <h4 className="text-xs font-bold text-slate-600">Select a Bug / Tip</h4>
                  <p className="text-[10px] text-slate-400 mt-1 max-w-[200px] leading-relaxed mx-auto">
                    Click a bug report or tip from the list on the left to review its details.
                  </p>
                </div>
              </div>
            )
          ) : (
            activeSource ? (
              <div className="max-w-3xl mx-auto space-y-6">
                
                {/* Header info card */}
                <div className="p-4 rounded-3xl bg-white border border-slate-200/80 flex items-center justify-between shadow-sm relative overflow-hidden shrink-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] font-black tracking-widest uppercase px-2 py-0.5 rounded border bg-amber-50 text-amber-700 border-amber-200">
                      Data Source Profile
                    </span>
                    <span className="text-xs text-slate-400 font-medium pl-1">
                      Target Table: <code className="font-mono text-slate-600 bg-slate-100 px-1 py-0.5 rounded">{activeSource.id}</code>
                    </span>
                  </div>
                  <div className="text-xs text-slate-500 font-bold bg-slate-100 px-3 py-1 rounded-xl">
                    {activeSource.count.toLocaleString()} Total Records
                  </div>
                </div>

                {/* Details Card */}
                <div className="bg-white border border-slate-200/80 rounded-3xl p-6 md:p-8 space-y-6 shadow-sm">
                  <div className="flex items-center gap-3.5">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center shadow-sm border bg-amber-50 border-amber-100 text-amber-600">
                      <Database className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="text-sm md:text-base font-extrabold text-slate-900 leading-snug">
                        {activeSource.name}
                      </h3>
                      <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-0.5">
                        Storage & Ingestion Metadata
                      </p>
                    </div>
                  </div>

                  <div className="border border-slate-100 rounded-2xl overflow-hidden bg-slate-50/50 text-xs">
                    <table className="min-w-full divide-y divide-slate-100">
                      <tbody>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider w-1/3 border-r border-slate-100">Source Identifier</td>
                          <td className="px-4 py-3 font-semibold text-slate-800 font-mono">{activeSource.id}</td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Storage Location</td>
                          <td className="px-4 py-3 font-semibold text-slate-800">{activeSource.db_source}</td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Last Ingested Record Date</td>
                          <td className="px-4 py-3 font-semibold text-slate-800">
                            {activeSource.last_updated ? new Date(activeSource.last_updated).toLocaleString() : 'No Ingestion Timestamp'}
                          </td>
                        </tr>
                        <tr className="hover:bg-slate-50 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wider border-r border-slate-100">Description</td>
                          <td className="px-4 py-3 font-medium text-slate-600 leading-relaxed">{activeSource.description}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <div className="pt-5 border-t border-slate-100 space-y-4">
                    <h4 className="text-[10px] font-black text-slate-400 uppercase tracking-widest pl-0.5">
                      Ingestion Architecture
                    </h4>
                    <p className="text-xs text-slate-500 leading-relaxed font-medium">
                      This table is populated via dedicated background crawlers located in the <code className="font-mono bg-slate-100 text-slate-700 px-1 py-0.5 rounded">services/scraper</code> directory. The ingested datasets are fully indexed and semantically embedded, allowing the PennerAI correlation engine to synthesize links between audit reports, council meeting actions, budgets, and legislation.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center text-center py-36 px-4 text-slate-400 space-y-3">
                <Database className="w-12 h-12 text-slate-300" />
                <div>
                  <h4 className="text-xs font-bold text-slate-600">Select a Data Source</h4>
                  <p className="text-[10px] text-slate-400 mt-1 max-w-[200px] leading-relaxed mx-auto">
                    Click a source from the list on the left to review its schema details, record volume, and database configurations.
                  </p>
                </div>
              </div>
            )
          )}
        </main>

      </div>
    </div>
  );
}
