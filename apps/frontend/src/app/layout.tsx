import './globals.css';
import React from 'react';
import { Outfit, Playfair_Display } from 'next/font/google';

const outfit = Outfit({
  subsets: ['latin'],
  variable: '--font-outfit',
  display: 'swap',
});

const playfair = Playfair_Display({
  subsets: ['latin'],
  variable: '--font-playfair',
  display: 'swap',
});

export const metadata = {
  title: 'PennerAI | Washington Civic Intelligence',
  description: 'Deep, conversational, fact-based answers on Washington State policies, local agendas, and municipal audits.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${outfit.variable} ${playfair.variable}`}>
      <body className="antialiased min-h-screen relative text-slate-900 font-sans">
        {children}
      </body>
    </html>
  );
}
