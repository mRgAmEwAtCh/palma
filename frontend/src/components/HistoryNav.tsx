import { NavLink } from 'react-router-dom'

/** Switch between run history and schedules (both live under the History tab). */
export function HistoryNav() {
  return (
    <div className="segmented">
      <NavLink to="/runs" end className={({ isActive }) => (isActive ? 'active' : '')}>
        Runs
      </NavLink>
      <NavLink to="/schedules" className={({ isActive }) => (isActive ? 'active' : '')}>
        Schedules
      </NavLink>
    </div>
  )
}
