/** Display repair only: never changes saved HTML or publishing content. */
const PLACEHOLDER = /\{\{?IMAGE_HERE\}?\}/gi
const IMG = /<img\b[^>]*>/gi

export function safeArticlePreviewHtml(html: string, imageUrl: string | null): string {
  const valid = typeof imageUrl === 'string' && /^https:\/\//i.test(imageUrl.trim())
  return html.replace(IMG, tag => {
    if (!PLACEHOLDER.test(tag)) return tag
    PLACEHOLDER.lastIndex = 0
    if (!valid) return ''
    return tag.replace(PLACEHOLDER, imageUrl!.trim())
  })
}
