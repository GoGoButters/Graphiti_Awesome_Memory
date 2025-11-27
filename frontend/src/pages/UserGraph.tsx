import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import apiClient from '../api/apiClient';
import GraphViewer from '../components/GraphViewer';

export default function UserGraph() {
    const { userId } = useParams();
    const [graphData, setGraphData] = useState<any>(null);

    useEffect(() => {
        if (userId) {
            apiClient.get(`/admin/users/${userId}/graph`).then(res => {
                // Transform data to cytoscape elements if needed
                // Assuming API returns { nodes: [], edges: [] } compatible with cytoscape or close to it
                setGraphData(res.data);
            });
        }
    }, [userId]);

    return (
        <div className="p-8">
            <h1 className="text-2xl font-bold mb-6">Graph for {userId}</h1>
            {graphData ? (
                <GraphViewer elements={[...graphData.nodes, ...graphData.edges]} />
            ) : (
                <p>Loading...</p>
            )}
        </div>
    );
}
