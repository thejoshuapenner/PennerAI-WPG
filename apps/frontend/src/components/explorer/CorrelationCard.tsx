'use client';

import React, { useState, useRef } from 'react';
import { ArrowRight } from 'lucide-react';

interface Correlation {
  jurisdiction: string;
  category: string;
  summary: string;
  dollar_impact?: number;
  similarity?: number;
  source: 'audit' | 'council' | 'bill' | 'grant';
}

interface CorrelationCardProps {
  correlation: Correlation;
  onClickInvestigate: (prompt: string) => void;
}

export const CorrelationCard: React.FC<CorrelationCardProps> = ({
  correlation,
  onClickInvestigate
}) => {
  const cardRef = useRef<HTMLDivElement>(null);
  const [transformStyle, setTransformStyle] = useState('perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)');
  const [shadowStyle, setShadowStyle] = useState('0 10px 20px rgba(0, 0, 0, 0.05), 0 2px 6px rgba(0, 0, 0, 0.03)');
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const card = cardRef.current;
    if (!card) return;

    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left; // x position within the element
    const y = e.clientY - rect.top;  // y position within the element

    // Calculate mouse position relative to center of card (-0.5 to 0.5)
    const xc = rect.width / 2;
    const yc = rect.height / 2;
    const dx = (x - xc) / xc; 
    const dy = (y - yc) / yc;

    // Calculate tilt angles (max 12 degrees rotation)
    const rotateY = dx * 12;
    const rotateX = -dy * 12;

    setTransformStyle(`perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.03, 1.03, 1.03)`);
    
    // Shift shadow dynamically in the opposite direction of tilt for physical realism
    const shadowX = -dx * 8;
    const shadowY = -dy * 8 + 15;
    setShadowStyle(`${shadowX}px ${shadowY}px 30px rgba(12, 90, 76, 0.15), 0 3px 8px rgba(0, 0, 0, 0.05)`);
  };

  const handleMouseEnter = () => {
    setIsHovered(true);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    setTransformStyle('perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)');
    setShadowStyle('0 10px 20px rgba(0, 0, 0, 0.05), 0 2px 6px rgba(0, 0, 0, 0.03)');
  };

  const sourceLabels = {
    audit: 'SAO Audit',
    council: 'City Council',
    bill: 'State Bill',
    grant: 'Grant Program'
  };

  const sourceColors = {
    audit: 'bg-purple-50 text-purple-700 border-purple-200',
    council: 'bg-blue-50 text-blue-700 border-blue-200',
    bill: 'bg-rose-50 text-rose-700 border-rose-200',
    grant: 'bg-emerald-50 text-emerald-700 border-emerald-200'
  };

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        transform: transformStyle,
        boxShadow: shadowStyle,
        transition: isHovered ? 'transform 0.08s ease-out, box-shadow 0.08s ease-out' : 'transform 0.5s ease, box-shadow 0.5s ease',
        transformStyle: 'preserve-3d',
      }}
      className="p-5 rounded-2xl border border-slate-200/80 bg-white space-y-4 relative overflow-hidden group shrink-0"
    >
      {/* Receipts Skeuomorphic Header strip */}
      <div className="absolute top-0 left-0 right-0 h-1.5 bg-gradient-to-r from-evergreen via-emerald-500 to-teal-600" />
      
      <div className="flex justify-between items-start" style={{ transform: 'translateZ(10px)' }}>
        <div>
          <div className="text-[10px] font-black uppercase text-evergreen tracking-wider font-sans">
            {correlation.jurisdiction}
          </div>
          <div className="text-[9px] font-extrabold text-slate-400 mt-0.5 uppercase tracking-wide">
            {correlation.category}
          </div>
        </div>
        {correlation.similarity !== undefined && (
          <div className="text-[10px] font-black text-emerald-800 bg-emerald-50 border border-emerald-200/40 px-2 py-0.5 rounded shadow-sm">
            {Math.round(correlation.similarity * 100)}% Match
          </div>
        )}
      </div>

      <p 
        className="text-xs text-slate-700 leading-relaxed font-semibold font-sans"
        style={{ transform: 'translateZ(15px)' }}
      >
        {correlation.summary}
      </p>

      {correlation.dollar_impact ? (
        <div 
          className="text-xs font-bold text-rose-700 flex items-center gap-1.5 bg-rose-50 border border-rose-100 py-1 px-3 rounded-xl w-fit shadow-sm"
          style={{ transform: 'translateZ(20px)' }}
        >
          <span className="w-1.5 h-1.5 bg-rose-500 rounded-full animate-pulse" />
          <span>Financial impact: ${correlation.dollar_impact.toLocaleString()}</span>
        </div>
      ) : null}

      <div 
        className="flex items-center gap-2 pt-1.5 shrink-0 border-t border-dashed border-slate-100"
        style={{ transform: 'translateZ(10px)' }}
      >
        <span className={`text-[8px] font-black tracking-widest uppercase px-2.5 py-1 rounded-full border shadow-sm ${sourceColors[correlation.source]}`}>
          {sourceLabels[correlation.source]}
        </span>
        <button
          onClick={() => onClickInvestigate(`Tell me more about the ${correlation.jurisdiction} ${correlation.category} findings.`)}
          className="text-[9px] font-black text-slate-500 hover:text-evergreen transition-colors uppercase ml-auto tracking-wider flex items-center gap-1 border-none bg-transparent cursor-pointer"
          type="button"
        >
          <span>Investigate</span>
          <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>
    </div>
  );
};
