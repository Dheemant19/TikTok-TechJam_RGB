import styles from "./Chart.module.css";

interface DataTableProps {
  caption: string;
  columns: string[];
  rows: (string | number)[][];
  onRowClick?: (rowIndex: number) => void;
}

/** Every chart's tooltip data is duplicated here for keyboard/screen-reader access. */
export function DataTable({ caption, columns, rows, onRowClick }: DataTableProps) {
  return (
    <table className={styles.dataTable}>
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column} scope="col">
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {row.map((cell, cellIndex) =>
              cellIndex === 0 && onRowClick ? (
                <th key={cellIndex} scope="row">
                  <button type="button" className={styles.rowLink} onClick={() => onRowClick(rowIndex)}>
                    {cell}
                  </button>
                </th>
              ) : cellIndex === 0 ? (
                <th key={cellIndex} scope="row">
                  {cell}
                </th>
              ) : (
                <td key={cellIndex}>{cell}</td>
              ),
            )}
          </tr>
        ))}
        {rows.length === 0 && (
          <tr>
            <td colSpan={columns.length}>No data was produced for this check.</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
