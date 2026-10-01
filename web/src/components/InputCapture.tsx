import { useEffect, useRef, useState } from 'react';

type Props = { source: string; onSource: (value: string) => void; text: string;
  onText: (value: string) => void; onFile: (file: File | null) => void };

export function InputCapture({ source, onSource, text, onText, onFile }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const [recording, setRecording] = useState(false);
  const [fileName, setFileName] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (source === 'handwriting' && canvas.current) {
      const context = canvas.current.getContext('2d')!;
      context.fillStyle = '#fff'; context.fillRect(0, 0, 1000, 300);
      context.strokeStyle = '#1c2521'; context.lineWidth = 4; context.lineCap = 'round';
    }
  }, [source]);
  useEffect(() => () => { if (recorder.current?.state === 'recording') recorder.current.stop(); stream.current?.getTracks().forEach(track => track.stop()); }, []);

  function changeSource(value: string) {
    if (recording) return;
    onSource(value); onFile(null); setFileName(''); setError('');
  }

  async function record() {
    setError('');
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Use an audio upload on this browser.');
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      const type = ['audio/webm', 'audio/mp4', 'audio/ogg'].find(mime => MediaRecorder.isTypeSupported(mime));
      recorder.current = new MediaRecorder(stream.current, type ? { mimeType: type } : undefined);
      const chunks: BlobPart[] = [];
      recorder.current.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.current.onstop = () => {
        const file = new File(chunks, 'voice-note', { type: recorder.current!.mimeType });
        onFile(file); setFileName('Voice note recorded'); setRecording(false);
        stream.current?.getTracks().forEach(track => track.stop());
      };
      recorder.current.start(); setRecording(true);
    } catch (failure) { setError(String(failure)); }
  }

  function saveDrawing() {
    canvas.current?.toBlob(blob => {
      if (blob) { onFile(new File([blob], 'handwriting.png', { type: 'image/png' })); setFileName('Handwriting captured'); }
    }, 'image/png');
  }

  return <div className="input-capture">
    <div className="segmented" aria-label="Input source">
      {['text', 'audio', 'handwriting'].map(type => <button type="button" key={type} aria-pressed={source === type}
        disabled={recording} onClick={() => changeSource(type)}>{type === 'audio' ? 'Voice' : type === 'handwriting' ? 'Handwriting' : 'Text'}</button>)}
    </div>
    {source === 'text' ? <label>Your note<textarea value={text} onChange={event => onText(event.target.value)}
      placeholder="What happened? Include what changed, what you checked, and the result." rows={4} /></label> : <>
      {source === 'audio' && <button className={recording ? 'danger' : 'secondary'} type="button"
        onClick={() => recording ? recorder.current?.stop() : void record()}>{recording ? 'Stop recording' : 'Record voice note'}</button>}
      {source === 'handwriting' && <>
        <p className="hint">Write below, or upload a photo of the note.</p>
        <canvas ref={canvas} width={1000} height={300} aria-label="Handwriting canvas"
          onPointerDown={event => {
            const bounds = event.currentTarget.getBoundingClientRect();
            const context = canvas.current!.getContext('2d')!;
            drawing.current = true; event.currentTarget.setPointerCapture(event.pointerId);
            context.beginPath(); context.moveTo((event.clientX - bounds.left) * 1000 / bounds.width, (event.clientY - bounds.top) * 300 / bounds.height);
          }}
          onPointerMove={event => {
            if (!drawing.current) return;
            const bounds = event.currentTarget.getBoundingClientRect();
            const context = canvas.current!.getContext('2d')!;
            context.lineTo((event.clientX - bounds.left) * 1000 / bounds.width, (event.clientY - bounds.top) * 300 / bounds.height); context.stroke();
          }}
          onPointerUp={() => { drawing.current = false; saveDrawing(); }}
          onPointerCancel={() => { drawing.current = false; saveDrawing(); }} />
        <button className="text-button" type="button" onClick={() => {
          const context = canvas.current!.getContext('2d')!; context.fillRect(0, 0, 1000, 300);
          onFile(null); setFileName('');
        }}>Clear handwriting</button>
      </>}
      <label className="file-input">Upload {source === 'audio' ? 'audio' : 'image'}<input type="file"
        accept={source === 'audio' ? 'audio/*' : 'image/png,image/jpeg,image/webp'}
        onChange={event => { const file = event.target.files?.[0] || null; onFile(file); setFileName(file?.name || ''); }} /></label>
      {fileName && <p className="hint">{fileName}</p>}
    </>}
    {error && <p role="alert" className="error">{error}</p>}
  </div>;
}
