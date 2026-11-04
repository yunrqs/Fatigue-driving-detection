interface Props {
  name: 'camera' | 'play' | 'pause' | 'image' | 'reset' | 'shield' | 'chevron' | 'eye' | 'target' | 'fullscreen' | 'tools' | 'chart';
}

// 所有图标使用相同尺寸和线条，颜色跟随按钮文字，不需要额外图标库。
export default function Icon({ name }: Props) {
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === 'camera' && <>
      <path d="M8 5 9.5 3h5L16 5h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z" />
      <circle cx="12" cy="12.5" r="4" />
    </>}
    {name === 'play' && <><circle cx="12" cy="12" r="9" /><path d="m10 8 6 4-6 4Z" /></>}
    {name === 'pause' && <><circle cx="12" cy="12" r="9" /><path d="M9 8v8M15 8v8" /></>}
    {name === 'image' && <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <circle cx="8" cy="8" r="1" /><path d="m3 17 5-5 4 4 4-6 5 7" />
    </>}
    {name === 'reset' && <><path d="M20 8a8 8 0 1 0 .5 7M20 3v5h-5" /></>}
    {name === 'shield' && <>
      <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z" /><path d="m8.5 12 2.5 2.5 4.5-5" />
    </>}
    {name === 'chevron' && <path d="m9 6 6 6-6 6" />}
    {name === 'eye' && <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>}
    {name === 'target' && <><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2" /><path d="M12 2v4m0 12v4M2 12h4m12 0h4" /></>}
    {name === 'fullscreen' && <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5" />}
    {name === 'tools' && <path d="m14 6 4 4 4-4a7 7 0 0 1-9 9l-6 6a3 3 0 0 1-4-4l6-6a7 7 0 0 1 9-9Z" />}
    {name === 'chart' && <><path d="M4 20h16" /><path d="M7 20v-6M12 20V8m5 12V12" /></>}
  </svg>;
}
