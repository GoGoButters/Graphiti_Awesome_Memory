import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import apiClient from '../api/apiClient';
import GraphViewer3D from '../components/GraphViewer3D';

export default function UserGraph() {
    const { userId } = useParams();
    const [elements, setElements] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshKey, setRefreshKey] = useState(0);

    const fetchGraph = () => {
        setLoading(true);
        apiClient.get(`/admin/users/${userId}/graph`)
            .then(res => {
                if (res.data && res.data.nodes && res.data.edges) {
                    setElements([...res.data.nodes, ...res.data.edges]);
                } else {
                    setElements([]);
                }
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    };

    useEffect(() => {
        fetchGraph();
    }, [userId, refreshKey]);

    // Auto-refresh when window gains focus (e.g., after deleting episodes on another tab)
    useEffect(() => {
        const handleFocus = () => {
            fetchGraph();
        };
        window.addEventListener('focus', handleFocus);
        return () => window.removeEventListener('focus', handleFocus);
    }, [userId]);

    if (loading) return <div className="p-8 text-white bg-gray-900 h-screen flex items-center justify-center">Loading graph...</div>;

    return (
        <div className="relative w-screen h-screen overflow-hidden bg-gray-900">
            <div className="absolute top-4 left-4 z-10 flex flex-col sm:flex-row gap-2">
                <button
                    onClick={() => window.history.back()}
                    className="bg-white/10 hover:bg-white/20 text-white px-3 py-2 sm:px-4 sm:py-2 rounded backdrop-blur-sm transition-colors border border-white/20 flex items-center gap-2 text-sm sm:text-base"
                >
                    ← <span className="hidden sm:inline">Back</span>
                </button>
                <button
                    onClick={() => setRefreshKey(prev => prev + 1)}
                    className="bg-white/10 hover:bg-white/20 text-white px-3 py-2 sm:px-4 sm:py-2 rounded backdrop-blur-sm transition-colors border border-white/20 flex items-center gap-2 text-sm sm:text-base"
                    title="Refresh graph"
                >
                    🔄 <span className="hidden sm:inline">Refresh</span>
                </button>
            </div>
            <div className="absolute top-4 right-4 z-10 pointer-events-none max-w-[200px] sm:max-w-none">
                <h1 className="text-sm sm:text-xl font-bold text-white/80 backdrop-blur-sm px-3 py-2 sm:px-4 sm:py-2 rounded bg-black/20 break-all">
                    Graph: {userId}
                </h1>
            </div>
            <GraphViewer3D elements={elements} />
        </div>
    );
}
