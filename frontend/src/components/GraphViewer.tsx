import { useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';

cytoscape.use(fcose);

interface GraphViewerProps {
    elements: any[];
}

export default function GraphViewer({ elements }: GraphViewerProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const cyRef = useRef<cytoscape.Core | null>(null);

    useEffect(() => {
        if (containerRef.current) {
            cyRef.current = cytoscape({
                container: containerRef.current,
                elements: elements,
                style: [
                    {
                        selector: 'node',
                        style: {
                            'background-color': '#666',
                            'label': 'data(label)'
                        }
                    },
                    {
                        selector: 'edge',
                        style: {
                            'width': 3,
                            'line-color': '#ccc',
                            'target-arrow-color': '#ccc',
                            'target-arrow-shape': 'triangle',
                            'curve-style': 'bezier'
                        }
                    }
                ],
                layout: {
                    name: 'fcose'
                }
            });
        }

        return () => {
            cyRef.current?.destroy();
        };
    }, [elements]);

    return <div ref={containerRef} className="w-full h-[600px] border rounded" />;
}
