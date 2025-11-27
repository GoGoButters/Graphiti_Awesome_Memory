import { useEffect, useState } from 'react';
import apiClient from '../api/apiClient';
import { Link } from 'react-router-dom';

export default function Dashboard() {
    const [stats, setStats] = useState<any>(null);

    useEffect(() => {
        apiClient.get('/admin/users').then(res => setStats(res.data));
    }, []);

    return (
        <div className="p-8">
            <h1 className="text-2xl font-bold mb-6">Dashboard</h1>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="bg-white p-6 rounded shadow">
                    <h3 className="text-gray-500 text-sm">Total Users</h3>
                    <p className="text-3xl font-bold">{stats?.total || 0}</p>
                </div>
                {/* Add more tiles */}
            </div>

            <div className="bg-white rounded shadow overflow-hidden">
                <table className="min-w-full">
                    <thead className="bg-gray-50">
                        <tr>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">User ID</th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Episodes</th>
                            <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {stats?.users?.map((user: any) => (
                            <tr key={user.user_id}>
                                <td className="px-6 py-4 whitespace-nowrap">{user.user_id}</td>
                                <td className="px-6 py-4 whitespace-nowrap">{user.episodes_count}</td>
                                <td className="px-6 py-4 whitespace-nowrap">
                                    <Link to={`/users/${user.user_id}/graph`} className="text-blue-600 hover:text-blue-900">View Graph</Link>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
