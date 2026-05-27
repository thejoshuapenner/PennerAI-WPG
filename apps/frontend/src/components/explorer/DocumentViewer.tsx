'use client';

import React from 'react';
import { X, ExternalLink, Building, FileText, Calendar, Landmark } from 'lucide-react';

interface Document {
  text: string;
  url: string;
  type: 'audit' | 'council' | 'web' | 'bill' | 'grant';
}

interface DocumentViewerProps {
  selectedDocument: Document | null;
  onClose: () => void;
  resizing?: boolean;
}

export const DocumentViewer: React.FC<DocumentViewerProps> = ({
  selectedDocument,
  onClose,
  resizing = false
}) => {
  if (!selectedDocument) return null;

  const docTypeLabels = {
    audit: 'SAO Audit File',
    council: 'City Council Action',
    bill: 'State Bill',
    grant: 'Grant Program',
    web: 'Web Citation'
  };

  const docTypeIcons = {
    audit: <FileText className="w-4 h-4 text-purple-600" />,
    council: <Landmark className="w-4 h-4 text-blue-600" />,
    bill: <Calendar className="w-4 h-4 text-rose-600" />,
    grant: <Building className="w-4 h-4 text-emerald-600" />,
    web: <FileText className="w-4 h-4 text-slate-600" />
  };

  // Helper to extract report number
  let reportNum = '';
  const apiMatch = selectedDocument.url.match(/\/api\/v1\/documents\/sao\/([^\/]+)\/pdf/);
  const urlMatch = selectedDocument.url.match(/\b\d{7}\b/);
  const textMatch = selectedDocument.text.match(/\b\d{7}\b/);
  
  if (apiMatch) {
    reportNum = apiMatch[1];
  } else if (urlMatch) {
    reportNum = urlMatch[0];
  } else if (textMatch) {
    reportNum = textMatch[0];
  }

  const renderIframe = () => {
    if (resizing) {
      return (
        <div className="flex-1 flex items-center justify-center bg-slate-50 text-slate-400 font-semibold text-xs animate-pulse">
          Adjusting layout...
        </div>
      );
    }

    if (reportNum) {
      return (
        <iframe 
          src={`/api/v1/documents/sao/${reportNum}/pdf#view=FitH`}
          className="w-full h-full border-none flex-1"
          title={selectedDocument.text}
        />
      );
    }

    if (selectedDocument.type === 'audit' || selectedDocument.url.endsWith('.pdf')) {
      return (
        <iframe 
          src={`https://docs.google.com/viewer?url=${encodeURIComponent(selectedDocument.url)}&embedded=true`}
          className="w-full h-full border-none flex-1"
          title={selectedDocument.text}
        />
      );
    }

    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center p-6 text-slate-400 bg-slate-50/50 space-y-4">
        <div className="p-3.5 bg-slate-100 rounded-full border border-slate-200/40 text-slate-400">
          <Building className="w-6 h-6" />
        </div>
        <div>
          <h5 className="text-xs font-black text-slate-800 uppercase tracking-wider">Web Reference</h5>
          <p className="text-[11px] text-slate-500 mt-2 max-w-[200px] leading-relaxed mx-auto font-medium">
            This resource is an external search query or web page. Security headers typically restrict inline embedding.
          </p>
        </div>
        <a 
          href={selectedDocument.url} 
          target="_blank" 
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl text-xs font-bold border border-slate-200 transition-all cursor-pointer shadow-sm no-underline"
        >
          <span>Open Web Source</span>
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>
    );
  };

  const headerContent = (
    <div className="p-4 border-b border-slate-200/80 bg-slate-50/50 flex flex-col gap-3 shrink-0">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          {docTypeIcons[selectedDocument.type] || <FileText className="w-4 h-4" />}
          <span className="text-[10px] font-black uppercase text-slate-500 tracking-wider">
            {docTypeLabels[selectedDocument.type] || 'Reference Document'}
          </span>
        </div>
        <button 
          onClick={onClose}
          className="p-1.5 hover:bg-slate-200/80 text-slate-400 hover:text-slate-700 rounded-lg transition-colors border-none bg-transparent cursor-pointer"
          aria-label="Close document viewer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <h4 className="text-xs md:text-sm font-extrabold text-slate-900 leading-snug">
        {selectedDocument.text}
      </h4>
      <a 
        href={selectedDocument.url} 
        target="_blank" 
        rel="noopener noreferrer"
        className="inline-flex items-center justify-center gap-2 w-full py-2.5 px-4 bg-evergreen hover:bg-emerald-700 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-evergreen/10 cursor-pointer no-underline"
      >
        <ExternalLink className="w-3.5 h-3.5" />
        <span>Open original document</span>
      </a>
    </div>
  );

  return (
    <>
      {/* Tablet/Mobile Slider Drawer (lg hidden) */}
      <div className="fixed inset-0 z-50 lg:hidden">
        {/* Backdrop */}
        <div 
          className="absolute inset-0 bg-slate-900/40 backdrop-blur-md transition-opacity duration-300"
          onClick={onClose}
        />
        {/* Sliding Panel */}
        <div className="absolute inset-y-0 right-0 w-full max-w-xl bg-white shadow-2xl flex flex-col h-full transform transition-transform duration-300">
          {headerContent}
          <div className="flex-1 overflow-hidden relative bg-white">
            {renderIframe()}
          </div>
        </div>
      </div>

      {/* Desktop Inline Render (hidden below lg) */}
      <div className="hidden lg:flex lg:flex-col lg:h-full lg:w-full">
        {headerContent}
        <div className="flex-1 overflow-hidden relative bg-white">
          {renderIframe()}
        </div>
      </div>
    </>
  );
};
