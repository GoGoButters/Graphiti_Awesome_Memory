import { useCallback, useEffect, useRef, useState } from 'react';
import apiClient from '../api/apiClient';

export interface CommunityStatus {
    status: 'idle' | 'running' | 'done' | 'error';
    error?: string | null;
    communities?: number | null;
    built?: number;
    last_built_at?: string | null;
}

interface Props {
    userId: string;
    /** 'dark' for the graph overlay, 'light' for regular pages */
    variant?: 'dark' | 'light';
    /** Called when a build started from this page finishes */
    onBuilt?: () => void;
}

const formatDate = (value?: string | null) => {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

export default function CommunityBuildControl({ userId, variant = 'light', onBuilt }: Props) {
    const [status, setStatus] = useState<CommunityStatus | null>(null);
    const lastStatus = useRef<string | undefined>();
    const onBuiltRef = useRef(onBuilt);
    onBuiltRef.current = onBuilt;

    const loadStatus = useCallback(() => {
        return apiClient
            .get(`/admin/users/${userId}/communities/status`)
            .then(res => {
                if (lastStatus.current === 'running' && res.data?.status === 'done') onBuiltRef.current?.();
                lastStatus.current = res.data?.status;
                setStatus(res.data);
            })
            .catch(() => undefined);
    }, [userId]);

    useEffect(() => {
        loadStatus();
    }, [loadStatus]);

    // Poll while a build is running (also picks up builds started elsewhere)
    useEffect(() => {
        if (status?.status !== 'running') return;
        const timer = window.setInterval(loadStatus, 5000);
        return () => window.clearInterval(timer);
    }, [status?.status, loadStatus]);

    const build = () => {
        const confirmed = window.confirm(
            'Построение сообществ сгруппирует сущности в тематические кластеры и запросит у LLM сводку для каждого. ' +
            'Для большого графа это сотни запросов и может занять от нескольких минут до часа. Продолжить?'
        );
        if (!confirmed) return;
        apiClient
            .post(`/admin/users/${userId}/communities/build`)
            .then(() => {
                lastStatus.current = 'running';
                setStatus(prev => ({ ...(prev || {}), status: 'running', error: null }));
            })
            .catch(err =>
                setStatus(prev => ({
                    ...(prev || {}),
                    status: 'error',
                    error: err?.response?.data?.detail || err?.message,
                }))
            );
    };

    const running = status?.status === 'running';
    const built = status?.built || 0;

    let info = '';
    if (running) info = 'Идёт построение…';
    else if (status?.status === 'error') info = `Ошибка: ${status.error || 'unknown'}`;
    else if (built > 0) info = `Сообществ: ${built} · ${formatDate(status?.last_built_at)}`;
    else if (status) info = 'Ещё не построены';

    const buttonClass =
        variant === 'dark'
            ? 'bg-purple-600/80 hover:bg-purple-600 text-white px-3 py-2 rounded backdrop-blur-sm transition-colors border border-purple-300/30 text-sm sm:text-base disabled:opacity-50'
            : 'bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 sm:px-4 rounded text-sm disabled:opacity-50 whitespace-nowrap';
    const infoClass =
        variant === 'dark'
            ? `text-xs sm:text-sm ${status?.status === 'error' ? 'text-red-300' : 'text-white/80'}`
            : `text-xs sm:text-sm ${status?.status === 'error' ? 'text-red-600 dark:text-red-400' : 'text-gray-500 dark:text-gray-400'}`;

    return (
        <div className="flex items-center gap-2 flex-wrap">
            <button onClick={build} disabled={running || !status} className={buttonClass}>
                {running ? '⏳ Строим сообщества…' : built > 0 ? '🧩 Перестроить сообщества' : '🧩 Построить сообщества'}
            </button>
            {info && <span className={infoClass}>{info}</span>}
        </div>
    );
}
