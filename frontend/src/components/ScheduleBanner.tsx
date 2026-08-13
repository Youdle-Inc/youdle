'use client'

import { Calendar, Clock } from 'lucide-react'

interface ScheduleBannerProps {
  lastCompletedAt?: string | null
}

function getNextTuesdayAt15Utc(): { formatted: string; relative: string } {
  const now = new Date()
  const dayOfWeek = now.getUTCDay() // 0 = Sunday, 2 = Tuesday

  // Calculate days until next Tuesday
  let daysUntilTuesday = (2 - dayOfWeek + 7) % 7

  // The repository cron is fixed at 15:00 UTC: 9 AM CST or 10 AM CDT.
  if (daysUntilTuesday === 0) {
    const currentHourUTC = now.getUTCHours()
    if (currentHourUTC >= 15) {
      daysUntilTuesday = 7 // Next Tuesday
    }
  }

  const nextTuesday = new Date(now)
  nextTuesday.setUTCDate(now.getUTCDate() + daysUntilTuesday)
  nextTuesday.setUTCHours(15, 0, 0, 0)

  // Format the date
  const formatted = nextTuesday.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/Chicago'
  })

  // Calculate relative time
  const diffMs = nextTuesday.getTime() - now.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))

  let relative: string
  if (diffDays === 0) {
    relative = diffHours <= 1 ? 'in less than an hour' : `in ${diffHours} hours`
  } else if (diffDays === 1) {
    relative = 'tomorrow'
  } else {
    relative = `in ${diffDays} days`
  }

  return { formatted, relative }
}

function formatLastGenerated(dateString: string | null | undefined): string {
  if (!dateString) return 'Never'

  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/Chicago'
  })
}

export function ScheduleBanner({ lastCompletedAt }: ScheduleBannerProps) {
  const nextRun = getNextTuesdayAt15Utc()
  const lastGenerated = formatLastGenerated(lastCompletedAt)

  return (
    <div className="w-full rounded-xl bg-stone-50 border border-stone-200 p-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Next Generation */}
        <div className="flex items-center gap-4">
          <div className="flex items-center justify-center w-12 h-12 rounded-lg bg-youdle-100">
            <Calendar className="w-6 h-6 text-youdle-600" />
          </div>
          <div>
            <p className="text-sm font-medium text-stone-500">Configured GitHub Schedule</p>
            <p className="text-lg font-semibold text-black">{nextRun.formatted}</p>
            <p className="text-sm text-stone-400">15:00 UTC · {nextRun.relative}</p>
          </div>
        </div>

        {/* Last Generated */}
        <div className="flex items-center gap-4">
          <div className="flex items-center justify-center w-12 h-12 rounded-lg bg-purple-100">
            <Clock className="w-6 h-6 text-purple-600" />
          </div>
          <div>
            <p className="text-sm font-medium text-stone-500">Last Dashboard Job</p>
            <p className="text-lg font-semibold text-black">{lastGenerated}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
