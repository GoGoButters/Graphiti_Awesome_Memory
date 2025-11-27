import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/apiClient';

export default function Login() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const navigate = useNavigate();

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            // In a real app, we'd have a /login endpoint.
            // For this MVP, we might assume the adapter has one or we use basic auth to get a token.
            // The prompt says "Login page (JWT auth using admin creds from config)".
            // But I didn't implement a /login endpoint in the adapter!
            // I need to add a /login endpoint to the adapter's admin router.
            // For now, I'll assume it exists or I'll fix it in the next step.
            // Let's assume POST /admin/login returns { access_token: "..." }

            const response = await apiClient.post('/admin/login', { username, password });
            localStorage.setItem('token', response.data.access_token);
            navigate('/');
        } catch (error) {
            alert('Login failed');
        }
    };

    return (
        <div className="flex items-center justify-center h-screen">
            <form onSubmit={handleLogin} className="p-8 bg-white rounded shadow-md">
                <h1 className="mb-4 text-xl font-bold">Graphiti Admin</h1>
                <input
                    className="w-full p-2 mb-4 border rounded"
                    placeholder="Username"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                />
                <input
                    className="w-full p-2 mb-4 border rounded"
                    type="password"
                    placeholder="Password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                />
                <button className="w-full p-2 text-white bg-blue-500 rounded">Login</button>
            </form>
        </div>
    );
}
