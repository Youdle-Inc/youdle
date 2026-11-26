'use client'

import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

interface Candidate { media_id: string; url: string; width: number; height: number }

export function PhotoControls({ postId, currentImageUrl }: { postId: string; currentImageUrl: string | null }) {
  const queryClient = useQueryClient()
  const [notes, setNotes] = useState('')
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  const [busy, setBusy] = useState<'generate' | 'publish' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const generate = async () => {
    setBusy('generate')
    setMessage(null)
    try {
      const result = await api.generatePostPhoto(postId, notes)
      setCandidate(result)
      setMessage(`Photo ready for review: ${result.width} × ${result.height} pixels. The live article has not changed.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Photo generation failed')
    } finally {
      setBusy(null)
    }
  }

  const publish = async () => {
    if (!candidate) return
    setBusy('publish')
    setMessage(null)
    try {
      await api.publishPostPhoto(postId, candidate.media_id)
      setCandidate(null)
      await queryClient.invalidateQueries({ queryKey: ['posts'] })
      setMessage('Photo published to the live article.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Photo publication failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="border-t border-stone-200 bg-white p-4">
      <label htmlFor={`photo-notes-${postId}`} className="block text-sm font-medium text-stone-900">
        Photo notes or changes
      </label>
      <textarea id={`photo-notes-${postId}`} value={notes} onChange={event => setNotes(event.target.value)}
        maxLength={600} rows={2} placeholder="Describe the scene or what to change before regenerating. No people."
        className="mt-2 w-full rounded-lg border border-stone-300 p-2 text-sm text-stone-900" />
      {candidate && (
        <div className="mt-3">
          <p className="mb-2 text-xs font-medium text-stone-600">New photo preview · {candidate.width} × {candidate.height}</p>
          <img src={candidate.url} alt="Candidate article photo" className="max-h-64 w-full rounded-lg object-contain" />
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={generate} disabled={busy !== null}
          className="rounded-lg bg-stone-100 px-3 py-2 text-sm font-medium text-stone-800 hover:bg-stone-200 disabled:opacity-50">
          {busy === 'generate' ? 'Generating…' : currentImageUrl || candidate ? 'Regenerate photo' : 'Generate photo'}
        </button>
        <button type="button" onClick={publish} disabled={!candidate || busy !== null}
          className="rounded-lg bg-green-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy === 'publish' ? 'Publishing…' : 'Publish photo'}
        </button>
      </div>
      {message && <p role="status" className="mt-2 text-sm text-stone-700">{message}</p>}
    </div>
  )
}
