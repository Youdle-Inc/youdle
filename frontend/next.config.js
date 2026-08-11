/** @type {import('next').NextConfig} */
const defaultApiUrl = process.env.NODE_ENV === 'development'
  ? 'http://localhost:8000'
  : 'https://youdle.vercel.app'

const nextConfig = {
  // Enable React strict mode for better development experience
  reactStrictMode: true,
  
  // Image optimization domains
  images: {
    domains: [
      'localhost',
      // Add your Supabase storage domain
      // 'your-project.supabase.co',
    ],
  },
  
  // Environment variables exposed to the browser
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || defaultApiUrl,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  },
}

module.exports = nextConfig



