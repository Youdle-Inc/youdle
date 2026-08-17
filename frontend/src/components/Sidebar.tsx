'use client'

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
  PlayCircle
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
    <aside className="fixed inset-y-0 left-0 z-50 w-64 bg-white border-r border-stone-200">
      {/* Logo */}
      <div className="flex items-center gap-3 px-6 py-5 border-b border-stone-200">
        <Image
          src="/img/youdle-logo-brand.svg"
          alt="Youdle Logo"
          width={40}
          height={40}
          className="w-10 h-10"
        />
        <div>
          <h1 className="text-lg font-bold text-stone-900 tracking-tight">Youdle</h1>
          <p className="text-xs text-stone-500">Blog Agent Dashboard</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="px-3 py-4 space-y-1">
        {navigation.map((item) => {
          const isActive = pathname === item.href ||
            (item.href !== '/' && pathname.startsWith(item.href))

          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150',
                isActive
                  ? 'bg-youdle-50 text-youdle-700 shadow-sm'
                  : 'text-stone-600 hover:text-stone-900 hover:bg-stone-50'
              )}
            >
              <item.icon className={cn(
                'w-5 h-5 transition-colors',
                isActive ? 'text-youdle-600' : 'text-stone-400'
              )} />
              {item.name}
            </Link>
          )
        })}
      </nav>

      {/* Status indicator */}
      <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-stone-200">
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-stone-50">
          <div className={cn('w-2 h-2 rounded-full', statusPresentation.dotClass)} />
          <span className="text-xs text-stone-600">{statusPresentation.label}</span>
        </div>
        <p className="text-xs text-stone-400 mt-2 px-3">{statusPresentation.detail}</p>
      </div>
    </aside>
  )
}

