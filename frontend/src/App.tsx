import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import UserGraph from './pages/UserGraph';
import UserEpisodes from './pages/UserEpisodes';
import Login from './pages/Login';

const PrivateRoute = ({ children }: { children: JSX.Element }) => {
    const token = localStorage.getItem('token');
    return token ? children : <Navigate to="/login" />;
};

function App() {
    return (
        <Router>
            <div className="min-h-screen bg-gray-50">
                <Routes>
                    <Route path="/login" element={<Login />} />
                    <Route path="/" element={
                        <PrivateRoute>
                            <Dashboard />
                        </PrivateRoute>
                    } />
                    <Route path="/users/:userId/graph" element={
                        <PrivateRoute>
                            <UserGraph />
                        </PrivateRoute>
                    } />
                    <Route path="/users/:userId/episodes" element={
                        <PrivateRoute>
                            <UserEpisodes />
                        </PrivateRoute>
                    } />
                </Routes>
            </div>
        </Router>
    );
}

export default App;
