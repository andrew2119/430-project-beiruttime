export function WatchIllustration({ label }: { label: string }) {
  return <svg className="watch-illustration" viewBox="0 0 480 600" role="img" aria-label={label}>
    <defs>
      <linearGradient id="strap" x1="0" x2="1"><stop stopColor="#091f1a"/><stop offset=".5" stopColor="#29584b"/><stop offset="1" stopColor="#102e26"/></linearGradient>
      <linearGradient id="steel" x1="0" x2="1" y1="0" y2="1"><stop stopColor="#d9c6a2"/><stop offset=".25" stopColor="#f6e6c3"/><stop offset=".55" stopColor="#9e8355"/><stop offset=".8" stopColor="#ead6ae"/><stop offset="1" stopColor="#a38c65"/></linearGradient>
      <radialGradient id="dial"><stop stopColor="#245247"/><stop offset="1" stopColor="#0b2b24"/></radialGradient>
      <filter id="shadow"><feDropShadow dx="0" dy="16" stdDeviation="18" floodOpacity=".28"/></filter>
    </defs>
    <g transform="rotate(-16 240 300)" filter="url(#shadow)">
      <path d="M184 18Q240 4 296 18L306 220H174ZM174 380H306L296 582Q240 596 184 582Z" fill="url(#strap)"/>
      <path d="M196 24L190 200M284 24L290 200M190 400L196 576M290 400L284 576" stroke="#8b9778" strokeWidth="1.5" strokeDasharray="4 5" opacity=".55"/>
      <path d="M162 185L174 161H306L318 185V415L306 439H174L162 415Z" fill="url(#steel)"/>
      <rect x="380" y="281" width="21" height="38" rx="5" fill="url(#steel)"/>
      <circle cx="240" cy="300" r="150" fill="url(#steel)"/>
      <circle cx="240" cy="300" r="139" fill="#7b694b"/>
      <circle cx="240" cy="300" r="134" fill="url(#dial)" stroke="#dfc9a1" strokeWidth="2"/>
      {Array.from({ length: 60 }, (_, i) => <line key={i} x1="240" y1="175" x2="240" y2={i % 5 === 0 ? 191 : 181} transform={`rotate(${i * 6} 240 300)`} stroke="#d3c39f" strokeWidth={i % 5 === 0 ? 3 : 1} />)}
      <text x="240" y="240" textAnchor="middle" fill="#ddcba5" fontFamily="Georgia,serif" fontSize="15" letterSpacing="3">BEIRUT TIME</text>
      <text x="240" y="350" textAnchor="middle" fill="#d3c39f" fontFamily="Georgia,serif" fontSize="9" letterSpacing="3">MECHANICAL</text>
      <line x1="240" y1="300" x2="191" y2="249" stroke="#edd9b2" strokeWidth="7" strokeLinecap="round"/>
      <line x1="240" y1="300" x2="315" y2="226" stroke="#edd9b2" strokeWidth="4" strokeLinecap="round"/>
      <line x1="240" y1="323" x2="240" y2="196" transform="rotate(142 240 300)" stroke="#b88657" strokeWidth="1.5"/>
      <circle cx="240" cy="300" r="6" fill="#edd9b2"/>
      <path d="M144 224Q210 159 306 205" fill="none" stroke="white" strokeWidth="20" opacity=".04"/>
    </g>
  </svg>;
}
