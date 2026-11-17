import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, X } from 'lucide-react'

export interface CustomSelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface CustomSelectGroup {
  label: string
  options: CustomSelectOption[]
}

interface CustomSelectProps {
  value: string
  onChange: (value: string) => void
  options?: CustomSelectOption[]
  groups?: CustomSelectGroup[]
  placeholder?: string
  disabled?: boolean
  className?: string
  style?: React.CSSProperties
  ariaLabel?: string
}

export function CustomSelect({
  value,
  onChange,
  options = [],
  groups = [],
  placeholder = '请选择…',
  disabled = false,
  className = '',
  style,
  ariaLabel,
}: CustomSelectProps) {
  const [open, setOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; minWidth: number; maxWidth: number }>({
    top: 0,
    left: 0,
    minWidth: 180,
    maxWidth: 360,
  })

  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)

  const allOptions = useMemo(() => {
    const list: CustomSelectOption[] = [...options]
    groups.forEach((g) => list.push(...g.options))
    return list
  }, [options, groups])

  const selectedOption = allOptions.find((opt) => opt.value === value)
  const displayLabel = selectedOption ? selectedOption.label : placeholder

  const updatePosition = () => {
    if (typeof window === 'undefined') return
    const mobile = window.innerWidth <= 768
    setIsMobile(mobile)
    if (!mobile && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const vw = window.innerWidth
      const vh = window.innerHeight
      const minW = Math.max(rect.width, 180)
      const maxW = Math.min(vw - 24, 420)
      let left = rect.left
      if (left + minW > vw - 12) {
        left = Math.max(12, vw - minW - 12)
      }
      const spaceBelow = vh - rect.bottom - 12
      const menuEstHeight = Math.min(280, Math.max(120, allOptions.length * 36 + 16))
      const top = spaceBelow < 180 && rect.top > spaceBelow
        ? Math.max(12, rect.top - menuEstHeight - 6)
        : rect.bottom + 6
      setMenuPos({ top, left, minWidth: minW, maxWidth: maxW })
    }
  }

  useEffect(() => {
    if (!open) return
    updatePosition()

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        triggerRef.current?.contains(target) ||
        menuRef.current?.contains(target)
      ) {
        return
      }
      setOpen(false)
    }
    const handleResize = () => updatePosition()

    document.addEventListener('keydown', handleKey)
    document.addEventListener('mousedown', handleClickOutside)
    window.addEventListener('resize', handleResize)
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.removeEventListener('mousedown', handleClickOutside)
      window.removeEventListener('resize', handleResize)
    }
  }, [open, allOptions.length])

  const renderOption = (opt: CustomSelectOption) => {
    const active = opt.value === value
    return (
      <button
        key={opt.value}
        type="button"
        role="option"
        aria-selected={active}
        disabled={opt.disabled}
        className={`custom-select-option ${active ? 'is-selected' : ''}`}
        onClick={() => {
          if (opt.disabled) return
          onChange(opt.value)
          setOpen(false)
        }}
      >
        <span className="custom-select-option-label">{opt.label}</span>
        {active && <Check size={14} className="custom-select-check" />}
      </button>
    )
  }

  const menuContent = (
    <>
      {options.map(renderOption)}
      {groups.map((grp) => (
        <div key={grp.label} className="custom-select-group">
          <div className="custom-select-group-label">{grp.label}</div>
          {grp.options.map(renderOption)}
        </div>
      ))}
    </>
  )

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`select-field custom-select-trigger ${open ? 'is-open' : ''} ${className}`}
        style={style}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => {
          if (!disabled) setOpen((prev) => !prev)
        }}
      >
        <span className="custom-select-value">{displayLabel}</span>
        <ChevronDown size={14} className={`custom-select-arrow ${open ? 'is-open' : ''}`} />
      </button>

      {open &&
        typeof document !== 'undefined' &&
        createPortal(
          isMobile ? (
            <div className="custom-select-backdrop" onClick={() => setOpen(false)}>
              <div
                ref={menuRef}
                className="custom-select-sheet"
                role="listbox"
                aria-label={ariaLabel}
                onClick={(e) => e.stopPropagation()}
              >
                <div className="custom-select-sheet-header">
                  <span>{ariaLabel || placeholder}</span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-circle btn-sm"
                    onClick={() => setOpen(false)}
                    aria-label="关闭"
                  >
                    <X size={16} />
                  </button>
                </div>
                <div className="custom-select-sheet-list">{menuContent}</div>
              </div>
            </div>
          ) : (
            <div
              ref={menuRef}
              className="custom-select-menu"
              role="listbox"
              aria-label={ariaLabel}
              style={{
                top: `${menuPos.top}px`,
                left: `${menuPos.left}px`,
                minWidth: `${menuPos.minWidth}px`,
                maxWidth: `${menuPos.maxWidth}px`,
              }}
            >
              {menuContent}
            </div>
          ),
          document.body
        )}
    </>
  )
}
