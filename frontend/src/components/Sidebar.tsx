'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  Search,
  FileText,
  CheckSquare,
  Settings,
  Activity,
  Mail,
  Image as ImageIcon,
  PlayCircle,
  Menu,
  X
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSystemHealth } from '@/lib/hooks/useSystemHealth'

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Articles', href: '/articles', icon: Search },
  { name: 'Blog Posts', href: '/posts', icon: FileText },
  { name: 'Media Library', href: '/media', icon: ImageIcon },
  { name: 'Newsletters', href: '/newsletters', icon: Mail },
  { name: 'Review', href: '/review', icon: CheckSquare },
  { name: 'Jobs', href: '/jobs', icon: Activity },
  { name: 'Actions', href: '/actions', icon: PlayCircle },
  { name: 'Settings', href: '/settings', icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()
  const { overallStatus } = useSystemHealth()
  const [isMobileOpen, setIsMobileOpen] = useState(false)

  useEffect(() => {
    setIsMobileOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!isMobileOpen) return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [isMobileOpen])

  const statusPresentation = {
    available: {
      dotClass: 'bg-green-500',
      label: 'System online',
      detail: 'API and database connected',
    },
    degraded: {
      dotClass: 'bg-amber-500',
      label: 'System degraded',
      detail: 'Database check failed',
    },
    unavailable: {
      dotClass: 'bg-red-500',
      label: 'System unavailable',
      detail: 'API checks failed',
    },
    checking: {
      dotClass: 'bg-yellow-500 animate-pulse',
      label: 'Checking system',
      detail: 'Contacting API and database',
    },
    unknown: {
      dotClass: 'bg-stone-400',
      label: 'Status unknown',
      detail: 'Live checks unavailable',
    },
  }[overallStatus]

  return (
    <>
      {/* Mobile header */}
      <header className="fixed inset-x-0 top-0 z-30 flex h-16 items-center justify-between border-b border-stone-200 bg-white px-4 md:hidden">
        <div className="flex min-w-0 items-center gap-2.5">
          <Image
            src="/img/youdle-logo-brand.svg"
            alt="Youdle Logo"
            width={32}
            height={32}
            className="h-8 w-8 flex-shrink-0"
          />
          <div className="min-w-0">
            <p className="truncate text-base font-bold tracking-tight text-stone-900">Youdle</p>
            <p className="truncate text-[11px] text-stone-500">Blog Agent Dashboard</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setIsMobileOpen(true)}
          className="rounded-lg p-2 text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
          aria-label="Open navigation"
          aria-expanded={isMobileOpen}
        >
          <Menu className="h-6 w-6" />
        </button>
      </header>

      {/* Mobile backdrop */}
      {isMobileOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/35 md:hidden"
          onClick={() => setIsMobileOpen(false)}
          aria-label="Close navigation"
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-stone-200 bg-white transition-transform duration-200 ease-out md:w-64 md:max-w-none md:translate-x-0',
          isMobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 border-b border-stone-200 px-5 py-5 md:px-6">
          <Image
            src="/img/youdle-logo-brand.svg"
            alt="Youdle Logo"
            width={40}
            height={40}
            className="h-10 w-10 flex-shrink-0"
          />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-lg font-bold tracking-tight text-stone-900">Youdle</h1>
            <p className="truncate text-xs text-stone-500">Blog Agent Dashboard</p>
          </div>
          <button
            type="button"
            onClick={() => setIsMobileOpen(false)}
            className="rounded-lg p-2 text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-900 md:hidden"
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {navigation.map((item) => {
            const isActive = pathname === item.href ||
              (item.href !== '/' && pathname.startsWith(item.href))

            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150',
                  isActive
                    ? 'bg-youdle-50 text-youdle-700 shadow-sm'
                    : 'text-stone-600 hover:bg-stone-50 hover:text-stone-900'
                )}
              >
                <item.icon className={cn(
                  'h-5 w-5 flex-shrink-0 transition-colors',
                  isActive ? 'text-youdle-600' : 'text-stone-400'
                )} />
                {item.name}
              </Link>
            )
          })}
        </nav>

        {/* Status indicator */}
        <div className="border-t border-stone-200 p-4">
          <div className="flex items-center gap-2 rounded-lg bg-stone-50 px-3 py-2">
            <div className={cn('h-2 w-2 rounded-full', statusPresentation.dotClass)} />
            <span className="text-xs text-stone-600">{statusPresentation.label}</span>
          </div>
          <p className="mt-2 px-3 text-xs text-stone-400">{statusPresentation.detail}</p>
        </div>
      </aside>
    </>
  )
}
