import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import apiClient from '../api/apiClient';
import GraphViewer3D, { GraphEdge, GraphNode } from '../components/GraphViewer3D';
import CommunityBuildControl from '../components/CommunityBuildControl';

const LIMIT_OPTIONS = [100, 300, 1000, 2000];
const DEFAULT_LIMIT = 300;
const COMMUNITY_COLOR = '#a855f7';

type ViewMode = 'entities' | 'communities';

interface GraphResponse {
    nodes: { data: GraphNode & { summary?: string; created_at?: string } }[];
    edges: { data: GraphEdge }[];
    total_nodes: number;
    total_edges: number;
    truncated: boolean;
    limit: number;
}

interface Community {
    uuid: string;
    name: string;
    summary: string;
    members: number;
}

const buttonClass =
    'bg-white/10 hover:bg-white/20 text-white px-3 py-2 sm:px-4 sm:py-2 rounded backdrop-blur-sm transition-colors border border-white/20 flex items-center gap-2 text-sm sm:text-base disabled:opacity-50';
const tabClass = (active: boolean) =>
    `px-3 py-2 sm:px-4 text-sm sm:text-base transition-colors ${active ? 'bg-white/90 text-gray-900 font-semibold' : 'text-white hover:bg-white/20'}`;

export default function UserGraph() {
    const { userId } = useParams();
    const [searchParams, setSearchParams] = useSearchParams();
    // Mode and selected community live in the URL so they can be linked to
    const mode: ViewMode = searchParams.get('mode') === 'communities' ? 'communities' : 'entities';
    const communityId = mode === 'communities' ? searchParams.get('community') : null;

    const [graph, setGraph] = useState<GraphResponse | null>(null);
    const [communities, setCommunities] = useState<Community[] | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [limit, setLimit] = useState<number>(() => {
        const fromQuery = Number(searchParams.get('limit'));
        if (LIMIT_OPTIONS.includes(fromQuery)) return fromQuery;
        const stored = Number(localStorage.getItem('graphLimit'));
        return LIMIT_OPTIONS.includes(stored) ? stored : DEFAULT_LIMIT;
    });
    const abortRef = useRef<AbortController | null>(null);

    const updateParams = (changes: Record<string, string | null>) => {
        const next = new URLSearchParams(searchParams);
        Object.entries(changes).forEach(([key, value]) => {
            if (value === null) next.delete(key);
            else next.set(key, value);
        });
        setSearchParams(next, { replace: true });
    };

    const startRequest = () => {
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;
        setLoading(true);
        setError(null);
        return controller;
    };

    const handleError = (err: any) => {
        if (err?.code === 'ERR_CANCELED') return; // aborted request, ignore
        const detail = err?.response?.data?.detail || err?.message || 'Неизвестная ошибка';
        setError(`Ошибка загрузки графа: ${detail}`);
        setLoading(false);
    };

    const fetchGraph = useCallback((lim: number, community: string | null) => {
        const controller = startRequest();
        const url = community
            ? `/admin/users/${userId}/communities/${community}/members`
            : `/admin/users/${userId}/graph`;
        apiClient
            .get(url, { params: { limit: lim }, signal: controller.signal })
            .then(res => {
                if (res.data && Array.isArray(res.data.nodes) && Array.isArray(res.data.edges)) {
                    setGraph(res.data);
                } else {
                    setError('Не удалось прочитать ответ сервера');
                }
                setLoading(false);
            })
            .catch(handleError);
    }, [userId]);

    const fetchCommunities = useCallback(() => {
        const controller = startRequest();
        apiClient
            .get(`/admin/users/${userId}/communities`, { signal: controller.signal })
            .then(res => {
                setCommunities(res.data?.communities || []);
                setLoading(false);
            })
            .catch(handleError);
    }, [userId]);

    const reload = useCallback(() => {
        if (mode === 'communities' && !communityId) fetchCommunities();
        else fetchGraph(limit, communityId);
    }, [mode, communityId, limit, fetchGraph, fetchCommunities]);

    useEffect(() => {
        reload();
        return () => abortRef.current?.abort();
    }, [reload]);

    // Community names for the banner when a community is opened by link
    useEffect(() => {
        if (!communityId || communities !== null) return;
        apiClient
            .get(`/admin/users/${userId}/communities`)
            .then(res => setCommunities(res.data?.communities || []))
            .catch(() => undefined);
    }, [communityId, communities, userId]);

    const handleLimitChange = (lim: number) => {
        setLimit(lim);
        localStorage.setItem('graphLimit', String(lim));
        updateParams({ limit: lim === DEFAULT_LIMIT ? null : String(lim) });
    };

    const handleModeChange = (next: ViewMode) => {
        updateParams({ mode: next === 'communities' ? 'communities' : null, community: null });
    };

    const handleBuilt = useCallback(() => {
        setCommunities(null);
        if (mode === 'communities' && !communityId) fetchCommunities();
    }, [mode, communityId, fetchCommunities]);

    const showCommunityOverview = mode === 'communities' && !communityId;
    const selectedCommunity = communityId ? (communities || []).find(c => c.uuid === communityId) : undefined;

    const nodes = useMemo<GraphNode[]>(() => {
        if (showCommunityOverview) {
            return (communities || []).map(c => ({
                id: c.uuid,
                label: `${c.name} (${c.members})`,
                degree: c.members,
                color: COMMUNITY_COLOR,
            }));
        }
        return (graph?.nodes || []).map(n => ({ ...n.data }));
    }, [showCommunityOverview, communities, graph]);

    const edges = useMemo<GraphEdge[]>(
        () => (showCommunityOverview ? [] : (graph?.edges || []).map(e => ({ ...e.data }))),
        [showCommunityOverview, graph]
    );

    const handleNodeClick = useCallback((nodeId: string) => {
        if (!showCommunityOverview) return;
        updateParams({ community: nodeId });
    }, [showCommunityOverview, searchParams]);

    const toolbar = userId && (
        <div className="absolute top-4 left-4 z-10 flex flex-col gap-2 max-w-[calc(100vw-2rem)]">
            <div className="flex flex-wrap gap-2">
                <button onClick={() => window.history.back()} className={buttonClass}>
                    ← <span className="hidden sm:inline">Back</span>
                </button>
                <button onClick={reload} className={buttonClass} title="Refresh graph">
                    🔄 <span className="hidden sm:inline">Refresh</span>
                </button>
                <div className="flex rounded overflow-hidden border border-white/30 backdrop-blur-sm bg-white/10" role="tablist">
                    <button role="tab" aria-selected={mode === 'entities'} onClick={() => handleModeChange('entities')} className={tabClass(mode === 'entities')}>
                        Сущности
                    </button>
                    <button role="tab" aria-selected={mode === 'communities'} onClick={() => handleModeChange('communities')} className={tabClass(mode === 'communities')}>
                        🧩 Сообщества
                    </button>
                </div>
                {!showCommunityOverview && (
                    <select
                        value={limit}
                        onChange={e => handleLimitChange(Number(e.target.value))}
                        className={`${buttonClass} [&>option]:bg-gray-800 [&>option]:text-white`}
                        title="Лимит узлов"
                    >
                        {LIMIT_OPTIONS.map(opt => (
                            <option key={opt} value={opt}>{opt} узлов</option>
                        ))}
                    </select>
                )}
                {communityId && (
                    <button onClick={() => updateParams({ community: null })} className={buttonClass}>
                        ↩ Все сообщества
                    </button>
                )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <CommunityBuildControl userId={userId} variant="dark" onBuilt={handleBuilt} />
                <Link to={`/users/${userId}/communities`} className="text-xs sm:text-sm text-purple-200 hover:text-white underline">
                    Список сообществ
                </Link>
            </div>
        </div>
    );

    if (loading) return <div className="p-8 text-white bg-gray-900 h-screen flex items-center justify-center">Loading graph...</div>;

    if (error) {
        return (
            <div className="w-screen h-screen bg-gray-900 flex items-center justify-center">
                <div className="text-center max-w-md px-6">
                    <h2 className="text-2xl font-bold text-white mb-4">Ошибка загрузки графа</h2>
                    <p className="text-red-400 mb-6 break-words">{error}</p>
                    <div className="flex justify-center gap-3">
                        <button onClick={() => window.history.back()} className={buttonClass}>← Назад</button>
                        <button onClick={reload} className={buttonClass}>🔄 Повторить</button>
                    </div>
                </div>
            </div>
        );
    }

    let banner: string | null = null;
    if (showCommunityOverview) {
        banner = communities && communities.length > 0
            ? `Сообществ: ${communities.length}. Нажмите на сообщество, чтобы открыть его участников`
            : null;
    } else if (graph?.truncated) {
        banner = `Показано ${graph.nodes.length} из ${graph.total_nodes} узлов (${graph.edges.length} связей)`;
    }
    if (communityId) {
        banner = `${selectedCommunity?.name || 'Сообщество'}: ${banner || `${nodes.length} узлов`}`;
    }

    const empty = nodes.length === 0;

    return (
        <div className="relative w-screen h-screen overflow-hidden bg-gray-900">
            {toolbar}
            <div className="absolute top-4 right-4 z-10 pointer-events-none max-w-[200px] sm:max-w-none hidden md:block">
                <h1 className="text-sm sm:text-xl font-bold text-white/80 backdrop-blur-sm px-3 py-2 sm:px-4 sm:py-2 rounded bg-black/20 break-all">
                    Graph: {userId}
                </h1>
            </div>
            {banner && (
                <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 bg-white/10 backdrop-blur-sm border border-white/20 rounded px-3 py-1.5 text-xs sm:text-sm text-white/90 max-w-[90vw] text-center">
                    {banner}
                </div>
            )}
            {empty ? (
                <div className="w-full h-full flex items-center justify-center">
                    <div className="text-center px-6 max-w-lg">
                        <h2 className="text-2xl font-bold text-white mb-4">
                            {showCommunityOverview ? 'Сообщества ещё не построены' : 'No Graph Data'}
                        </h2>
                        <p className="text-gray-400">
                            {showCommunityOverview
                                ? 'Нажмите «🧩 Построить сообщества» слева вверху, чтобы сгруппировать сущности в тематические кластеры со сводками.'
                                : 'This user has no entities or relationships yet.'}
                        </p>
                    </div>
                </div>
            ) : (
                <GraphViewer3D nodes={nodes} edges={edges} onNodeClick={handleNodeClick} />
            )}
        </div>
    );
}
