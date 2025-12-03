import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import apiClient from '../api/apiClient';
import GitHubButton from '../components/GitHubButton';

export default function Login() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const navigate = useNavigate();

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const response = await apiClient.post('/admin/login', { username, password });
            localStorage.setItem('token', response.data.access_token);
            navigate('/');
        } catch (error) {
            alert('Login failed');
        }
    };

    return (
        <>
            <GitHubButton />
            <div className="flex items-center justify-center min-h-screen bg-gray-900 p-4">
                <form onSubmit={handleLogin} className="w-full max-w-md p-6 sm:p-8 bg-gray-800 rounded-lg shadow-xl border border-gray-700">
                    <h1 className="mb-6 text-xl sm:text-2xl font-bold text-white text-center">Graphiti Awesome Memory</h1>
                    <input
                        className="w-full p-3 mb-4 bg-gray-700 border border-gray-600 rounded text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="Username"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                    />
                    <input
                        className="w-full p-3 mb-6 bg-gray-700 border border-gray-600 rounded text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        type="password"
                        placeholder="Password"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                    />
                    <button className="w-full p-3 text-white bg-blue-600 rounded hover:bg-blue-700 transition-colors font-medium">Login</button>
                </form>
            </div>
        </>
    );
}
