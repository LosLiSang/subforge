import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Play, Clock } from 'lucide-react'
import type { Item } from '../types'

export interface WorkCardProps {
  item: Item
  onQuickPlay?: (e: React.MouseEvent, item: Item) => void
  className?: string
}

/**
 * Format seconds to asmr.one style duration (e.g., "1.8h" or "45m")
 */
function formatDuration(seconds?: number, fallbackLabel?: string): string | null {
  if (typeof seconds === 'number' && seconds > 0) {
    const hours = seconds / 3600
    if (hours >= 1) {
      return `${hours.toFixed(1)}h`
    }
    const mins = Math.round(seconds / 60)
    return `${mins}m`
  }
  if (fallbackLabel) {
    return fallbackLabel
  }
  return null
}

export function WorkCard({
  item,
  onQuickPlay,
  className = '',
}: WorkCardProps) {
  const navigate = useNavigate()
  const [imgError, setImgError] = useState(false)

  React.useEffect(() => {
    setImgError(false)
  }, [item.cover_url, item.updated_at])

  const handlePlayClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (onQuickPlay) {
      onQuickPlay(e, item)
    }
  }

  const circles = item.creators?.filter((c) => c.kind === 'circle') || []
  const voiceActors = item.creators?.filter((c) => c.kind === 'voice_actor') || []
  const durationText = formatDuration(item.total_duration, item.total_duration_label)
  const displayDate = item.release_date || (item.created_at ? item.created_at.slice(0, 10) : null)
  const coverSrc = imgError || !item.cover_url
    ? '/covers/default'
    : (item.cover_url.includes('?v=')
        ? item.cover_url
        : `${item.cover_url}${item.updated_at ? (item.cover_url.includes('?') ? `&v=${encodeURIComponent(item.updated_at)}` : `?v=${encodeURIComponent(item.updated_at)}`) : ''}`)

  return (
    <Link
      to={`/items/${item.item_id}`}
      className={`asmr-card ${className}`}
      title={item.title}
    >
      {/* Cover Area */}
      <div className="asmr-card-cover-wrap">
        <img
          className="asmr-card-cover-img"
          src={coverSrc}
          alt={item.title}
          loading="lazy"
          onError={(e) => {
            if (!imgError) {
              setImgError(true)
            } else {
              (e.target as HTMLImageElement).src = '/static/subforge-icon.svg'
            }
          }}
        />

        {/* Top Left: RJ Code badge and Favorite button */}
        {item.rj_code && (
          <div className="asmr-card-top-left">
            <span className="asmr-card-badge-rj" title={`RJ号: ${item.rj_code}`}>
              {item.rj_code}
            </span>
          </div>
        )}

        {/* Bottom Right: Release Date */}
        {displayDate && (
          <div className="asmr-card-bottom-date">
            {displayDate}
          </div>
        )}

        {/* Hover Quick Play Button */}
        {onQuickPlay && (
          <button
            type="button"
            className="asmr-card-quick-play"
            onClick={handlePlayClick}
            title="一键播放"
            aria-label="一键播放"
          >
            <Play size={20} fill="currentColor" style={{ marginLeft: 2 }} />
          </button>
        )}
      </div>

      {/* Body Area */}
      <div className="asmr-card-body">
        <h3 className="asmr-card-title">{item.title}</h3>

        {/* Tags & Badges Area */}
        <div className="asmr-card-tags">
          {/* General Tags */}
          {item.tags && item.tags.slice(0, 7).map((t, idx) => (
            <span
              key={`tag-${idx}`}
              className="asmr-tag asmr-tag-default asmr-tag-clickable"
              title={`标签: ${t} (点击筛选)`}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                navigate(`/library?tag=${encodeURIComponent(t)}`)
              }}
            >
              {t}
            </span>
          ))}

          {/* Circle Badges (Orange) */}
          {circles.map((c) => (
            <span
              key={c.creator_id}
              className="asmr-tag asmr-tag-circle asmr-tag-clickable"
              title={`社团: ${c.name} (点击筛选)`}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                navigate(`/library?creator=${c.creator_id}`)
              }}
            >
              {c.name}
            </span>
          ))}

          {/* Voice Actor Badges (Green) */}
          {voiceActors.map((c) => (
            <span
              key={c.creator_id}
              className="asmr-tag asmr-tag-va asmr-tag-clickable"
              title={`声优: ${c.name} (点击筛选)`}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                navigate(`/library?creator=${c.creator_id}`)
              }}
            >
              {c.name}
            </span>
          ))}

          {/* Duration Badge */}
          {durationText && (
            <span className="asmr-tag asmr-tag-duration">
              <Clock size={12} style={{ marginRight: 3 }} />
              {durationText}
            </span>
          )}
        </div>
      </div>
    </Link>
  )
}
