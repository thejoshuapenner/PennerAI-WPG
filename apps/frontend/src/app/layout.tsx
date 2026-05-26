import './globals.css';
import React from 'react';

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
    <html lang="en">
      <body className="antialiased min-h-screen relative text-mist">
        {children}
      </body>
    </html>
  );
}
