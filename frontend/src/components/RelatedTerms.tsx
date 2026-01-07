import { useState, useEffect } from 'react'
import { graphApi, type RelatedTerm, type PopularTerm } from '@/services/api'

interface RelatedTermsProps {
  currentQuery: string
  onTermClick: (term: string) => void
  className?: string
}

export function RelatedTerms({ currentQuery, onTermClick, className = '' }: RelatedTermsProps) {
  const [relatedTerms, setRelatedTerms] = useState<RelatedTerm[]>([])
  const [popularTerms, setPopularTerms] = useState<PopularTerm[]>([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'related' | 'popular'>('related')

  useEffect(() => {
    if (currentQuery && currentQuery.trim().length > 0) {
      fetchRelatedTerms(currentQuery)
      setActiveTab('related')
    } else {
      fetchPopularTerms()
      setActiveTab('popular')
    }
  }, [currentQuery])

  const fetchRelatedTerms = async (query: string) => {
    setLoading(true)
    try {
      const terms = await graphApi.getRelatedTerms(query, 8)
      setRelatedTerms(terms)
    } catch (error) {
      console.warn('Failed to fetch related terms:', error)
      setRelatedTerms([])
    } finally {
      setLoading(false)
    }
  }

  const fetchPopularTerms = async () => {
    setLoading(true)
    try {
      const terms = await graphApi.getPopularTerms(10)
      setPopularTerms(terms)
    } catch (error) {
      console.warn('Failed to fetch popular terms:', error)
      setPopularTerms([])
    } finally {
      setLoading(false)
    }
  }

  const handleTermClick = (term: string) => {
    onTermClick(term)
  }

  // Don't render if no data
  const hasRelatedTerms = relatedTerms.length > 0
  const hasPopularTerms = popularTerms.length > 0

  if (!hasRelatedTerms && !hasPopularTerms && !loading) {
    return null
  }

  return (
    <div className={`bg-white/5 backdrop-blur-sm rounded-xl border border-white/10 p-4 ${className}`}>
      {/* Tab Header */}
      <div className="flex items-center gap-2 mb-3">
        {currentQuery && (
          <button
            onClick={() => setActiveTab('related')}
            className={`px-3 py-1.5 text-sm rounded-lg transition-all ${
              activeTab === 'related'
                ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                : 'text-gray-400 hover:text-gray-300 hover:bg-white/5'
            }`}
          >
            <span className="flex items-center gap-1.5">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              Related
            </span>
          </button>
        )}
        <button
          onClick={() => {
            setActiveTab('popular')
            if (popularTerms.length === 0) {
              fetchPopularTerms()
            }
          }}
          className={`px-3 py-1.5 text-sm rounded-lg transition-all ${
            activeTab === 'popular'
              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
              : 'text-gray-400 hover:text-gray-300 hover:bg-white/5'
          }`}
        >
          <span className="flex items-center gap-1.5">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            Popular
          </span>
        </button>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center py-4">
          <div className="w-5 h-5 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin" />
        </div>
      )}

      {/* Related Terms */}
      {!loading && activeTab === 'related' && (
        <div className="space-y-2">
          {hasRelatedTerms ? (
            <>
              <p className="text-xs text-gray-500 mb-2">
                Based on search patterns for "{currentQuery}"
              </p>
              <div className="flex flex-wrap gap-2">
                {relatedTerms.map((term, index) => (
                  <button
                    key={`${term.term}-${index}`}
                    onClick={() => handleTermClick(term.term)}
                    className="group flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-purple-500/10 to-pink-500/10 hover:from-purple-500/20 hover:to-pink-500/20 border border-purple-500/20 hover:border-purple-500/40 rounded-full text-sm text-gray-300 hover:text-white transition-all"
                  >
                    <span>{term.term}</span>
                    <span className="text-xs text-purple-400/60 group-hover:text-purple-400">
                      ({term.cooccurrence})
                    </span>
                  </button>
                ))}
              </div>
            </>
          ) : currentQuery ? (
            <p className="text-sm text-gray-500 text-center py-2">
              No related terms found yet. Keep searching to build connections!
            </p>
          ) : null}
        </div>
      )}

      {/* Popular Terms */}
      {!loading && activeTab === 'popular' && (
        <div className="space-y-2">
          {hasPopularTerms ? (
            <>
              <p className="text-xs text-gray-500 mb-2">
                Trending search terms
              </p>
              <div className="flex flex-wrap gap-2">
                {popularTerms.map((term, index) => (
                  <button
                    key={`${term.term}-${index}`}
                    onClick={() => handleTermClick(term.term)}
                    className="group flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-amber-500/10 to-orange-500/10 hover:from-amber-500/20 hover:to-orange-500/20 border border-amber-500/20 hover:border-amber-500/40 rounded-full text-sm text-gray-300 hover:text-white transition-all"
                  >
                    <span>{term.term}</span>
                    <span className="text-xs text-amber-400/60 group-hover:text-amber-400">
                      ({term.count})
                    </span>
                  </button>
                ))}
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500 text-center py-2">
              No popular terms yet. Start searching to see trends!
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default RelatedTerms
