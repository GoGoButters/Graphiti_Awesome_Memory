import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import apiClient from '../api/apiClient';
import GraphViewer3D from '../components/GraphViewer3D';

export default function UserGraph() {
    const { userId } = useParams();
    const [elements, setElements] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        apiClient.get(`/admin/users/${userId}/graph`)
            .then(res => {
                setElements(res.data);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    }, [userId]);

    if (loading) return <div className="p-8">Loading graph...</div>;

    return (
        <div className="p-8">
            <h1 className="text-2xl font-bold mb-6">Knowledge Graph: {userId}</h1>
            <GraphViewer3D elements={elements} />
        </div>
    );
}
