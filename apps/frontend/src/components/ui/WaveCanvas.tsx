'use client';

import React, { useEffect, useRef } from 'react';

export const WaveCanvas = React.memo(() => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

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

    const handleMouseMoveCanvas = (e: MouseEvent) => {
      mouseX = e.clientX;
      mouseY = e.clientY;
    };

    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', handleMouseMoveCanvas);
    resize();

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      
      const gridGradient = ctx.createRadialGradient(mouseX, mouseY, 50, mouseX, mouseY, 450);
      gridGradient.addColorStop(0, 'rgba(12, 90, 76, 0.40)'); // Richer glow near cursor
      gridGradient.addColorStop(0.4, 'rgba(12, 90, 76, 0.20)');
      gridGradient.addColorStop(0.8, 'rgba(12, 90, 76, 0.08)');
      gridGradient.addColorStop(1, 'rgba(12, 90, 76, 0.00)');
      ctx.strokeStyle = gridGradient;
      ctx.lineWidth = 1.0;
      
      const rows = 15;
      const cols = 25;
      const xSpacing = width / cols;
      const ySpacing = height / rows;

      // Draw horizontal lines
      for (let r = 0; r <= rows; r++) {
        const yBase = r * ySpacing;
        ctx.beginPath();
        for (let c = 0; c <= cols; c++) {
          const x = c * xSpacing;
          const dx = x - mouseX;
          const dy = yBase - mouseY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const mouseInfluence = Math.max(0, 400 - dist) / 400;
          
          const waveX = Math.sin(x * 0.003 + time) * 15;
          const waveY = Math.cos(yBase * 0.003 + time) * 15;
          const bulge = Math.pow(mouseInfluence, 2.5) * -50;

          const finalY = yBase + waveY + (bulge * (dy / (dist || 1)));
          const finalX = x + waveX + (bulge * (dx / (dist || 1)));

          if (c === 0) {
            ctx.moveTo(finalX, finalY);
          } else {
            ctx.lineTo(finalX, finalY);
          }
        }
        ctx.stroke();
      }

      // Draw vertical lines
      for (let c = 0; c <= cols; c++) {
        const xBase = c * xSpacing;
        ctx.beginPath();
        for (let r = 0; r <= rows; r++) {
          const y = r * ySpacing;
          const dx = xBase - mouseX;
          const dy = y - mouseY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const mouseInfluence = Math.max(0, 400 - dist) / 400;
          
          const waveX = Math.sin(xBase * 0.003 + time) * 15;
          const waveY = Math.cos(y * 0.003 + time) * 15;
          const bulge = Math.pow(mouseInfluence, 2.5) * -50;

          const finalY = y + waveY + (bulge * (dy / (dist || 1)));
          const finalX = xBase + waveX + (bulge * (dx / (dist || 1)));

          if (r === 0) {
            ctx.moveTo(finalX, finalY);
          } else {
            ctx.lineTo(finalX, finalY);
          }
        }
        ctx.stroke();
      }

      time += 0.006;
      animationFrameId = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', handleMouseMoveCanvas);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <canvas 
      ref={canvasRef} 
      className="fixed inset-0 w-full h-full pointer-events-none z-0 opacity-100 transition-opacity duration-1000" 
    />
  );
});

WaveCanvas.displayName = 'WaveCanvas';
